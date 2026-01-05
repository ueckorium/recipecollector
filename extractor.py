"""Extracts recipes from media using Gemini AI."""

import ipaddress
import json
import logging
import re
import socket
import subprocess
import tempfile
import time as time_module
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import PIL.Image
import requests
from bs4 import BeautifulSoup
from google import genai

from config import Config

logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Timeouts (in seconds)
TIMEOUT_WEBPAGE = 15
TIMEOUT_METADATA = 60
TIMEOUT_VIDEO_DOWNLOAD = 120

# Text length limits
MAX_WEBPAGE_TEXT = 6000
MAX_FETCH_TEXT = 4000
MIN_CONTENT_LENGTH = 100
MIN_SUBTITLE_LENGTH = 20

# HTTP session for connection reuse
_http_session: requests.Session | None = None


def _get_http_session() -> requests.Session:
    """Returns a reusable HTTP session."""
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        _http_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
    return _http_session


def _validate_and_resolve_url(url: str) -> tuple[bool, str | None, str | None]:
    """
    Validates URL against SSRF attacks and resolves DNS.

    Returns:
        Tuple of (is_valid, resolved_ip, hostname)
        - is_valid: True if URL is safe
        - resolved_ip: Resolved IP address (for DNS rebinding protection)
        - hostname: Original hostname for Host header
    """
    try:
        parsed = urlparse(url)

        # Only allow HTTP(S)
        if parsed.scheme not in ("http", "https"):
            logger.warning(f"Invalid URL scheme: {parsed.scheme}")
            return False, None, None

        # Hostname must be present
        if not parsed.hostname:
            logger.warning("URL without hostname")
            return False, None, None

        hostname = parsed.hostname
        hostname_lower = hostname.lower()

        # Block localhost variants
        blocked_hosts = ["localhost", "127.0.0.1", "0.0.0.0", "::1"]
        if hostname_lower in blocked_hosts:
            logger.warning(f"Blocked hostname: {hostname_lower}")
            return False, None, None

        # Resolve DNS and check IP
        try:
            resolved_ip = socket.gethostbyname(hostname)
            ip_obj = ipaddress.ip_address(resolved_ip)

            # Block private and reserved IP ranges
            if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
                logger.warning(f"Private/reserved IP blocked: {resolved_ip}")
                return False, None, None

            # Block Link-Local (169.254.x.x - Cloud Metadata)
            if ip_obj.is_link_local:
                logger.warning(f"Link-Local IP blocked: {resolved_ip}")
                return False, None, None

        except socket.gaierror:
            logger.warning(f"DNS resolution failed for: {hostname}")
            return False, None, None

        return True, resolved_ip, hostname

    except Exception as e:
        logger.warning(f"URL validation failed: {e}")
        return False, None, None


def _is_safe_url(url: str) -> bool:
    """Validates URL against SSRF attacks (wrapper for compatibility)."""
    is_valid, _, _ = _validate_and_resolve_url(url)
    return is_valid


def _safe_request(url: str, timeout: int = TIMEOUT_WEBPAGE) -> requests.Response:
    """
    Performs a secure HTTP request with DNS rebinding protection.

    Resolves DNS once and uses the IP directly for the request,
    to prevent DNS rebinding attacks.

    Raises:
        ValueError: For unsafe URL
        requests.RequestException: For HTTP errors
    """
    is_valid, resolved_ip, hostname = _validate_and_resolve_url(url)

    if not is_valid or not resolved_ip or not hostname:
        raise ValueError(f"Unsafe URL blocked: {url}")

    # Create URL with resolved IP (DNS rebinding protection)
    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    # Build URL with IP instead of hostname
    if parsed.port:
        ip_url = f"{parsed.scheme}://{resolved_ip}:{parsed.port}{parsed.path}"
    else:
        ip_url = f"{parsed.scheme}://{resolved_ip}{parsed.path}"

    if parsed.query:
        ip_url += f"?{parsed.query}"

    session = _get_http_session()

    # Request with correct Host header (for Virtual Hosts)
    headers = {"Host": hostname if not parsed.port else f"{hostname}:{parsed.port}"}

    response = session.get(ip_url, timeout=timeout, headers=headers, verify=True)
    response.raise_for_status()

    return response


def _fetch_webpage_text(url: str, max_length: int = MAX_FETCH_TEXT) -> str | None:
    """Fetches webpage content and extracts text (internal helper function)."""
    try:
        # SSRF protection with DNS rebinding protection
        response = _safe_request(url, timeout=TIMEOUT_WEBPAGE)

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove script/style
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()

        # Extract text
        text = soup.get_text(separator="\n", strip=True)

        # Clean blank lines
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)

        # Limit length
        if len(text) > max_length:
            text = text[:max_length] + "..."

        logger.info(f"Webpage fetched: {len(text)} characters")
        return text

    except Exception as e:
        logger.warning(f"Could not fetch webpage: {e}")
        return None


# =============================================================================
# DATA MODEL
# =============================================================================

@dataclass
class VideoMetadata:
    """Video metadata from yt-dlp."""
    title: str | None = None
    description: str | None = None
    uploader: str | None = None
    duration: int | None = None  # Seconds
    tags: list[str] = field(default_factory=list)
    subtitles: str | None = None  # Extracted subtitle text
    platform: str | None = None  # youtube, tiktok, instagram


@dataclass
class Recipe:
    """Complete recipe with all extracted information."""
    title: str
    servings: str | None = None
    prep_time: str | None = None
    cook_time: str | None = None
    total_time: str | None = None
    difficulty: str | None = None  # easy, medium, hard
    tags: list[str] = field(default_factory=list)
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    equipment: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # Tips, variations
    source_url: str | None = None
    source_platform: str | None = None  # tiktok, youtube, instagram, web
    creator: str | None = None


class NotARecipeError(ValueError):
    """Raised when content does not contain a valid recipe."""
    pass


def extract_recipe_from_video(
    config: Config,
    video_path: Path,
    source_url: str | None = None,
    metadata: VideoMetadata | None = None,
) -> Recipe:
    """
    Extracts a recipe directly from a video using Gemini.
    Uses all available metadata for maximum accuracy.
    """
    client = genai.Client(api_key=config.gemini.api_key)

    logger.info(f"Uploading video: {video_path}")
    video_file = client.files.upload(file=str(video_path))

    logger.info("Waiting for processing...")
    while video_file.state.name == "PROCESSING":
        time_module.sleep(2)
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        raise ValueError("Video upload failed")

    # Build structured prompt with all available sources
    prompt = config.prompts.extraction
    prompt += "\n\n" + "=" * 60
    prompt += "\nAVAILABLE SOURCES:"
    prompt += "\n" + "=" * 60

    if metadata:
        if metadata.subtitles:
            prompt += f"\n\n### 1. SUBTITLES/CAPTIONS (highest priority for quantities!):\n{metadata.subtitles}"

        if metadata.description:
            prompt += f"\n\n### 2. VIDEO DESCRIPTION:\n{metadata.description}"

        if metadata.title:
            prompt += f"\n\n### 3. VIDEO TITLE: {metadata.title}"

        if metadata.uploader:
            prompt += f"\n### 4. CREATOR: {metadata.uploader}"

        if metadata.tags:
            prompt += f"\n### 5. TAGS: {', '.join(metadata.tags[:10])}"

    if source_url:
        prompt += f"\n\n### SOURCE URL: {source_url}"

    prompt += "\n\n" + "=" * 60
    prompt += "\nNow analyze the video together with the sources above."

    logger.info("Sending to Gemini for analysis...")
    response = client.models.generate_content(
        model=config.gemini.model,
        contents=[video_file, prompt],
    )

    # Cleanup
    try:
        client.files.delete(name=video_file.name)
    except Exception as e:
        logger.debug(f"Could not delete temporary file: {e}")

    recipe = _parse_response(response.text, source_url)

    # Add metadata to recipe
    if metadata:
        recipe.source_platform = metadata.platform
        recipe.creator = metadata.uploader

    return recipe


def is_video_platform_url(url: str) -> bool:
    """
    Checks if URL is from a supported video platform.

    Args:
        url: The URL to check.

    Returns:
        True if URL is from TikTok, Instagram, YouTube or Facebook.
    """
    video_domains = [
        "tiktok.com",
        "vm.tiktok.com",
        "instagram.com",
        "youtube.com",
        "youtu.be",
        "facebook.com",
        "fb.watch",
    ]
    return any(domain in url.lower() for domain in video_domains)


def detect_platform(url: str) -> str | None:
    """
    Detects the video platform from URL.

    Args:
        url: The URL to analyze.

    Returns:
        Platform name ('tiktok', 'instagram', 'youtube', 'facebook') or None.
    """
    url_lower = url.lower()
    if "tiktok.com" in url_lower:
        return "tiktok"
    elif "instagram.com" in url_lower:
        return "instagram"
    elif "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "facebook.com" in url_lower or "fb.watch" in url_lower:
        return "facebook"
    return None


def extract_video_metadata(url: str, temp_dir: Path) -> VideoMetadata:
    """Extracts all available metadata from a video."""
    metadata = VideoMetadata(platform=detect_platform(url))

    # URL validation before subprocess call
    if not _is_safe_url(url):
        logger.warning(f"Unsafe URL blocked for yt-dlp: {url}")
        return metadata

    try:
        # Extract metadata as JSON
        result = subprocess.run(
            [
                "yt-dlp",
                "--no-download",
                "--dump-json",
                "--",  # Argument injection protection
                url,
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_METADATA,
        )

        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            metadata.title = data.get("title")
            metadata.description = data.get("description")
            metadata.uploader = data.get("uploader") or data.get("channel")
            metadata.duration = data.get("duration")
            metadata.tags = data.get("tags", []) or []

            logger.info(f"Metadata extracted: {metadata.title}")

    except subprocess.TimeoutExpired:
        logger.warning("Metadata extraction timeout")
    except json.JSONDecodeError:
        logger.warning("Could not parse metadata JSON")
    except Exception as e:
        logger.warning(f"Metadata extraction failed: {e}")

    # Extract subtitles (separate, as not always available)
    try:
        subs_path = temp_dir / "subs"
        result = subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-lang", "de,en",
                "--sub-format", "vtt/srt/best",
                "-o", str(subs_path),
                "--",  # Argument injection protection
                url,
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_METADATA,
        )

        # Search for downloaded subtitle files
        for ext in [".vtt", ".srt", ".de.vtt", ".en.vtt", ".de.srt", ".en.srt"]:
            sub_file = temp_dir / f"subs{ext}"
            if sub_file.exists():
                raw_subs = sub_file.read_text(encoding="utf-8", errors="ignore")
                metadata.subtitles = _clean_subtitles(raw_subs)
                if metadata.subtitles:
                    logger.info(f"Subtitles extracted: {len(metadata.subtitles)} characters")
                break

    except subprocess.TimeoutExpired:
        logger.warning("Subtitle extraction timeout")
    except Exception as e:
        logger.warning(f"Subtitle extraction failed: {e}")

    return metadata


def _clean_subtitles(raw_subs: str) -> str | None:
    """Cleans VTT/SRT subtitles to readable text."""
    if not raw_subs:
        return None

    lines = []
    seen = set()

    for line in raw_subs.splitlines():
        # Skip timestamps, WEBVTT header, empty lines
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("NOTE"):
            continue
        if re.match(r"^\d{2}:\d{2}", line):  # Timestamp
            continue
        if re.match(r"^\d+$", line):  # Sequence number
            continue
        if "-->" in line:  # Timestamp range
            continue

        # Remove VTT formatting
        line = re.sub(r"<[^>]+>", "", line)
        line = re.sub(r"\{[^}]+\}", "", line)

        # Deduplicate (subtitles often repeat)
        if line and line not in seen:
            seen.add(line)
            lines.append(line)

    text = " ".join(lines)
    return text if len(text) > MIN_SUBTITLE_LENGTH else None


def download_video_from_url(url: str, output_path: Path, temp_dir: Path) -> tuple[Path | None, VideoMetadata]:
    """Downloads video from URL with yt-dlp and extracts all metadata."""

    # URL validation before subprocess call
    if not _is_safe_url(url):
        logger.warning(f"Unsafe URL blocked for video download: {url}")
        return None, VideoMetadata(platform=detect_platform(url))

    # First extract all metadata
    metadata = extract_video_metadata(url, temp_dir)

    try:
        # Download video
        result = subprocess.run(
            [
                "yt-dlp",
                "-f", "best[ext=mp4]/best",
                "--no-playlist",
                "-o", str(output_path),
                "--",  # Argument injection protection
                url,
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_VIDEO_DOWNLOAD,
        )

        if result.returncode == 0 and output_path.exists():
            logger.info(f"Video downloaded: {output_path} ({output_path.stat().st_size // 1024}KB)")
            return output_path, metadata

        logger.warning(f"yt-dlp download error: {result.stderr}")
        return None, metadata

    except subprocess.TimeoutExpired:
        logger.warning("Video download timeout")
        return None, metadata
    except FileNotFoundError:
        logger.warning("yt-dlp not installed")
        return None, metadata
    except Exception as e:
        logger.warning(f"Video download failed: {e}")
        return None, metadata


def extract_recipe_from_metadata(
    config: Config,
    metadata: VideoMetadata,
    source_url: str,
) -> Recipe:
    """
    Extracts a recipe ONLY from video metadata (without video).
    Used when video download fails but metadata is available.
    """
    client = genai.Client(api_key=config.gemini.api_key)

    # Build structured prompt with all available sources
    prompt = config.prompts.extraction
    prompt += "\n\n" + "=" * 60
    prompt += "\nAVAILABLE SOURCES (no video available, text only):"
    prompt += "\n" + "=" * 60

    has_content = False

    if metadata.subtitles:
        prompt += f"\n\n### 1. SUBTITLES/CAPTIONS (highest priority for quantities!):\n{metadata.subtitles}"
        has_content = True

    if metadata.description:
        prompt += f"\n\n### 2. VIDEO DESCRIPTION:\n{metadata.description}"
        has_content = True

    if metadata.title:
        prompt += f"\n\n### 3. VIDEO TITLE: {metadata.title}"
        has_content = True

    if metadata.uploader:
        prompt += f"\n### 4. CREATOR: {metadata.uploader}"

    if metadata.tags:
        prompt += f"\n### 5. TAGS: {', '.join(metadata.tags[:10])}"

    prompt += f"\n\n### SOURCE URL: {source_url}"

    if not has_content:
        raise ValueError("No metadata available for extraction")

    prompt += "\n\n" + "=" * 60
    prompt += "\nNOTE: Video could not be downloaded. Extract the recipe from the text sources above."

    logger.info("Sending metadata to Gemini (without video)...")
    response = client.models.generate_content(
        model=config.gemini.model,
        contents=[prompt],
    )

    recipe = _parse_response(response.text, source_url)

    # Add metadata to recipe
    recipe.source_platform = metadata.platform
    recipe.creator = metadata.uploader

    return recipe


def extract_recipe_from_url(
    config: Config,
    url: str,
) -> Recipe:
    """
    Extracts a recipe from a URL.
    For video platforms (TikTok, Instagram, YouTube) the video is downloaded.
    Fallback order: Video > Metadata > Webpage
    """
    # For video platforms: download and analyze video
    if is_video_platform_url(url):
        logger.info(f"Video platform detected, downloading video: {url}")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_path = temp_path / "video.mp4"
            downloaded, metadata = download_video_from_url(url, video_path, temp_path)

            if downloaded:
                return extract_recipe_from_video(config, downloaded, url, metadata)

            # Video download failed - but do we have metadata?
            if metadata and (metadata.description or metadata.subtitles or metadata.title):
                logger.info("Video download failed, using extracted metadata...")
                try:
                    return extract_recipe_from_metadata(config, metadata, url)
                except Exception as e:
                    logger.warning(f"Metadata extraction failed: {e}")

            logger.warning("Neither video nor metadata available, trying webpage text...")

    # Webpage extraction: Try schema first, then text
    return extract_recipe_from_webpage(config, url)


def extract_recipe_schema(html: str) -> Recipe | None:
    """
    Extracts recipe from JSON-LD Schema (schema.org/Recipe).
    Many recipe sites have perfectly structured data!
    """
    soup = BeautifulSoup(html, "html.parser")

    # Search JSON-LD scripts
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)

            # Can be a single object or a list
            if isinstance(data, list):
                for item in data:
                    recipe = _parse_schema_recipe(item)
                    if recipe:
                        return recipe
            else:
                # Can also contain @graph
                if "@graph" in data:
                    for item in data["@graph"]:
                        recipe = _parse_schema_recipe(item)
                        if recipe:
                            return recipe
                else:
                    recipe = _parse_schema_recipe(data)
                    if recipe:
                        return recipe

        except (json.JSONDecodeError, TypeError):
            continue

    return None


def _parse_schema_recipe(data: dict) -> Recipe | None:
    """Parses a single JSON-LD Recipe object."""
    if not isinstance(data, dict):
        return None

    # Check if it's a Recipe
    schema_type = data.get("@type", "")
    if isinstance(schema_type, list):
        if "Recipe" not in schema_type:
            return None
    elif schema_type != "Recipe":
        return None

    # Extract fields
    title = data.get("name", "")
    if not title:
        return None

    # Ingredients
    ingredients = []
    raw_ingredients = data.get("recipeIngredient", [])
    if isinstance(raw_ingredients, list):
        ingredients = [str(i).strip() for i in raw_ingredients if i]

    # Instructions
    instructions = []
    raw_instructions = data.get("recipeInstructions", [])
    if isinstance(raw_instructions, list):
        for item in raw_instructions:
            if isinstance(item, str):
                instructions.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    instructions.append(text.strip())
    elif isinstance(raw_instructions, str):
        instructions = [s.strip() for s in raw_instructions.split("\n") if s.strip()]

    # Parse times (ISO 8601 Duration: PT30M, PT1H30M, etc.)
    def parse_duration(iso_str: str | None) -> str | None:
        if not iso_str:
            return None
        match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", iso_str)
        if match:
            hours = int(match.group(1) or 0)
            mins = int(match.group(2) or 0)
            if hours and mins:
                return f"{hours}h {mins}min"
            elif hours:
                return f"{hours}h"
            elif mins:
                return f"{mins} min"
        return None

    prep_time = parse_duration(data.get("prepTime"))
    cook_time = parse_duration(data.get("cookTime"))
    total_time = parse_duration(data.get("totalTime"))

    # Servings
    servings = None
    yield_val = data.get("recipeYield")
    if yield_val:
        if isinstance(yield_val, list):
            servings = str(yield_val[0])
        else:
            servings = str(yield_val)

    # Tags/Category
    tags = []
    if data.get("recipeCategory"):
        cat = data["recipeCategory"]
        if isinstance(cat, list):
            tags.extend(cat)
        else:
            tags.append(cat)
    if data.get("recipeCuisine"):
        cuisine = data["recipeCuisine"]
        if isinstance(cuisine, list):
            tags.extend(cuisine)
        else:
            tags.append(cuisine)
    if data.get("keywords"):
        kw = data["keywords"]
        if isinstance(kw, str):
            tags.extend([k.strip() for k in kw.split(",") if k.strip()])

    # Creator/Author
    creator = None
    author = data.get("author")
    if author:
        if isinstance(author, dict):
            creator = author.get("name")
        elif isinstance(author, str):
            creator = author

    logger.info(f"Schema recipe found: {title}")

    return Recipe(
        title=title,
        servings=servings,
        prep_time=prep_time,
        cook_time=cook_time,
        total_time=total_time,
        tags=tags[:10],  # Limit tags
        ingredients=ingredients,
        instructions=instructions,
        creator=creator,
        source_platform="web",
    )


def extract_recipe_from_webpage(config: Config, url: str) -> Recipe:
    """
    Extracts a recipe from a webpage.
    Tries JSON-LD Schema first, then falls back to Gemini.
    """
    try:
        # SSRF protection with DNS rebinding protection
        response = _safe_request(url, timeout=TIMEOUT_WEBPAGE)
        html = response.text
    except Exception as e:
        raise ValueError(f"Could not fetch webpage: {e}")

    # Try schema first (much more accurate!)
    recipe = extract_recipe_schema(html)
    if recipe:
        recipe.source_url = url
        logger.info("Recipe extracted from schema (high accuracy)")
        return recipe

    # Fallback: Extract text and send to Gemini
    logger.info("No schema found, using Gemini...")

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()

    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    text = "\n".join(lines)

    if len(text) > MAX_WEBPAGE_TEXT:
        text = text[:MAX_WEBPAGE_TEXT] + "..."

    if len(text) < MIN_CONTENT_LENGTH:
        raise ValueError("Could not retrieve sufficient content from webpage")

    client = genai.Client(api_key=config.gemini.api_key)

    prompt = config.prompts.extraction
    prompt += f"\n\nSource URL: {url}"
    prompt += f"\n\n--- Webpage Content ---\n{text}"

    logger.info("Sending webpage text to Gemini...")
    response = client.models.generate_content(
        model=config.gemini.model,
        contents=[prompt],
    )

    recipe = _parse_response(response.text, url)
    recipe.source_platform = "web"
    return recipe


def extract_recipe_from_image(
    config: Config,
    image_path: Path,
    source_url: str | None = None,
) -> Recipe:
    """
    Extracts a recipe from an image using Gemini.
    """
    client = genai.Client(api_key=config.gemini.api_key)

    # Load image
    image = PIL.Image.open(image_path)

    prompt = config.prompts.extraction

    # Fetch webpage content if URL provided
    if source_url:
        prompt += f"\n\nSource URL: {source_url}"
        webpage_text = _fetch_webpage_text(source_url)
        if webpage_text:
            prompt += f"\n\n--- Webpage Content ---\n{webpage_text}"

    logger.info("Sending image to Gemini...")
    response = client.models.generate_content(
        model=config.gemini.model,
        contents=[image, prompt],
    )

    return _parse_response(response.text, source_url)


def _parse_response(response_text: str, source_url: str | None) -> Recipe:
    """Parses the Gemini response to a Recipe object."""
    response_text = response_text.strip()

    # Extract JSON from response (remove potential markdown code blocks)
    if "```" in response_text:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", response_text, re.DOTALL)
        if match:
            response_text = match.group(1)

    try:
        data = json.loads(response_text)
    except json.JSONDecodeError as e:
        logger.error(f"Could not parse JSON: {response_text[:500]}")
        raise ValueError(f"Gemini did not return valid JSON: {e}")

    # Validate and create Recipe
    recipe = Recipe(
        title=data.get("title", "Unknown Recipe"),
        servings=data.get("servings"),
        prep_time=data.get("prep_time"),
        cook_time=data.get("cook_time"),
        total_time=data.get("total_time") or data.get("time"),  # Fallback for old format
        difficulty=data.get("difficulty"),
        tags=data.get("tags", []),
        ingredients=data.get("ingredients", []),
        instructions=data.get("instructions", []),
        equipment=data.get("equipment", []),
        notes=data.get("notes", []),
        source_url=source_url,
    )

    # Validation
    _validate_recipe(recipe)

    return recipe


def _validate_recipe(recipe: Recipe) -> None:
    """Validates a recipe and raises NotARecipeError if invalid."""
    has_title = recipe.title and recipe.title != "Unknown Recipe"
    has_ingredients = bool(recipe.ingredients)
    has_instructions = bool(recipe.instructions)

    # Must have both ingredients AND instructions to be useful
    if not has_ingredients or not has_instructions:
        raise NotARecipeError("Recipe is incomplete (missing ingredients or instructions)")

    warnings = []
    if not has_title:
        warnings.append("No title found")

    # Check for obviously missing quantities
    ingredients_without_amounts = 0
    for ing in recipe.ingredients:
        if not ing.startswith("## "):  # Ignore group headers
            # Has no number at the start
            if not re.match(r"^\d", ing.strip()):
                ingredients_without_amounts += 1

    if ingredients_without_amounts > len(recipe.ingredients) * 0.7:
        warnings.append(f"{ingredients_without_amounts} ingredients without quantities")

    if warnings:
        logger.warning(f"Recipe validation: {', '.join(warnings)}")


def _escape_telegram_markdown(text: str) -> str:
    r"""Escapes special characters for Telegram Markdown V1: \ * _ ` ["""
    if not text:
        return ""
    for char in ('\\', '*', '_', '`', '['):
        text = text.replace(char, f'\\{char}')
    return text


def format_recipe_chat(recipe: Recipe) -> str:
    """Formats a recipe for Telegram chat with proper Markdown escaping."""
    esc = _escape_telegram_markdown

    lines = [f"*{esc(recipe.title)}*", ""]

    # Meta line with all available info
    meta = []
    time_str = recipe.total_time or recipe.cook_time
    if time_str:
        meta.append(f"⏱ {esc(time_str)}")
    if recipe.servings:
        meta.append(f"👥 {esc(recipe.servings)}")
    if recipe.difficulty:
        difficulty_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(recipe.difficulty.lower(), "")
        meta.append(f"{difficulty_emoji} {esc(recipe.difficulty)}")
    if meta:
        lines.append(" | ".join(meta))

    if recipe.tags:
        tags_str = " ".join(f"#{esc(tag.replace(' ', '_'))}" for tag in recipe.tags[:8])
        lines.append(f"🏷 {tags_str}")

    lines.append("")
    lines.append("📋 *Ingredients:*")
    for ingredient in recipe.ingredients:
        if ingredient.startswith("## "):
            lines.append(f"\n*{esc(ingredient[3:])}*")
        else:
            lines.append(f"• {esc(ingredient)}")

    lines.append("")
    lines.append("👨‍🍳 *Instructions:*")
    for i, step in enumerate(recipe.instructions, 1):
        lines.append(f"{i}. {esc(step)}")

    if recipe.equipment:
        lines.append("")
        lines.append(f"🍳 *Equipment:* {esc(', '.join(recipe.equipment))}")

    if recipe.notes:
        lines.append("")
        lines.append("💡 *Tips:*")
        for note in recipe.notes:
            lines.append(f"• {esc(note)}")

    if recipe.source_url:
        lines.append("")
        creator_text = esc(recipe.creator) if recipe.creator else "Source"
        source_info = f"[{creator_text}]({recipe.source_url})"
        lines.append(f"🔗 {source_info}")

    return "\n".join(lines)


# =============================================================================
# COOKLANG FORMATTING - Pre-compiled patterns for performance
# =============================================================================

_COOKLANG_TIME_PATTERN = re.compile(
    r'\b(\d+(?:\s*-\s*\d+)?)\s*'
    r'(Minuten?|Min\.?|minutes?|min\.?|'
    r'Stunden?|Std\.?|hours?|hrs?\.?|'
    r'Sekunden?|Sek\.?|seconds?|sec\.?|secs?\.?)\b',
    re.IGNORECASE
)

_COOKLANG_PREP_WORDS = re.compile(
    r'gehackt|geschnitten|gewürfelt|gerieben|gepresst|gehobelt|'
    r'zerkleinert|püriert|gestampft|mariniert|eingeweicht|'
    r'aufgetaut|zimmerwarm|kalt|warm|weich|hart|frisch|getrocknet|'
    r'chopped|diced|minced|sliced|grated|pressed|crushed|'
    r'softened|melted|room temperature|cold|warm|fresh|dried',
    re.IGNORECASE
)

# Simplified pattern with length limits to prevent ReDoS
_COOKLANG_INGREDIENT_PATTERN = re.compile(
    r'^(\d[\d.,/\s-]{0,20})\s*([a-zA-ZäöüÄÖÜß]{1,15})?\s+(.+)$'
)


def _yaml_escape(value: str) -> str:
    """Escapes a value for safe YAML output."""
    if not value:
        return '""'
    # Quote if contains special YAML characters
    if any(c in value for c in ':{}[]&*#?|-<>=!%@`"\'\n\r\t'):
        escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return f'"{escaped}"'
    return value


def _extract_timers_from_text(text: str) -> str:
    """Converts time expressions to Cooklang timer format ~{amount%unit}.

    Examples: "5 Minuten" -> "~{5%Minuten}", "1-2 hours" -> "~{1-2%hours}"
    """
    return _COOKLANG_TIME_PATTERN.sub(
        lambda m: f"~{{{m.group(1).replace(' ', '')}%{m.group(2)}}}",
        text
    )


def _mark_items_in_text(text: str, items: list[str], prefix: str) -> str:
    """Marks items (ingredients/equipment) in text with Cooklang syntax.

    Args:
        text: Text to mark up
        items: List of item names to find and mark
        prefix: Cooklang prefix ('@' for ingredients, '#' for equipment)

    Only marks items that aren't already marked.
    Uses Unicode-aware word boundaries for proper German umlaut support.
    """
    text_lower = text.lower()  # Cache for performance
    seen = set()

    for name in sorted(set(items), key=len, reverse=True):  # Dedupe + sort
        if not name or len(name) < 2:
            continue
        name_lower = name.lower()
        if name_lower in seen:
            continue
        seen.add(name_lower)

        # Skip if already marked
        if f"{prefix}{name_lower}" in text_lower:
            continue

        # Unicode-aware word boundaries (lookahead/lookbehind)
        text = re.sub(
            rf'(?<![a-zA-ZäöüÄÖÜßéèêëàâáãåæçñ])({re.escape(name)})(?![a-zA-ZäöüÄÖÜßéèêëàâáãåæçñ])',
            rf'{prefix}\1{{}}',
            text,
            flags=re.IGNORECASE,
            count=1
        )
        text_lower = text.lower()  # Update cache after modification

    return text


def _extract_ingredient_names(ingredients: list[str]) -> list[str]:
    """Extracts ingredient names (without amounts/units) for matching."""
    names = []
    for ing in ingredients:
        if ing.startswith("## "):
            continue
        # Remove preparation hints in parentheses or after comma
        clean = re.sub(r'\s*[,(].*$', '', ing)
        # Extract name from "amount unit name" pattern, or use whole string
        match = re.match(r'^[\d.,/\s-]+\s*[a-zA-ZäöüÄÖÜß]*\s+(.+)$', clean)
        name = (match.group(1) if match else clean).strip()
        if name:
            names.append(name)
    return names


def format_recipe_cooklang(recipe: Recipe) -> str:
    """Formats a recipe in Cooklang format (.cook).

    Implements Cooklang spec features:
    - YAML frontmatter for metadata
    - @ingredient{amount%unit} syntax
    - @ingredient{}(preparation) for prep hints
    - #cookware{} for equipment
    - ~{time%unit} for timers
    - == Section == for grouping
    """
    lines = []

    # YAML Frontmatter for metadata (with escaping for security)
    metadata_map = {
        'source': recipe.source_url,
        'author': recipe.creator,
        'servings': recipe.servings,
        'prep time': recipe.prep_time,
        'cook time': recipe.cook_time,
        'time required': recipe.total_time,
        'difficulty': recipe.difficulty,
    }
    metadata_lines = [f"{key}: {_yaml_escape(str(val))}" for key, val in metadata_map.items() if val]

    if recipe.tags:
        metadata_lines.append("tags:")
        metadata_lines.extend(f"  - {_yaml_escape(tag)}" for tag in recipe.tags)

    if metadata_lines:
        lines.extend(["---", *metadata_lines, "---", ""])

    # Ingredients section
    if recipe.ingredients:
        lines.extend(["== Ingredients ==", ""])
        for ingredient in recipe.ingredients:
            if ingredient.startswith("## "):
                lines.extend([f"== {ingredient[3:]} ==", ""])
            else:
                lines.append(f"- {_convert_ingredient_to_cooklang(ingredient)}")
        lines.append("")

    # Instructions with ingredient/equipment/timer markup
    if recipe.instructions:
        lines.extend(["== Instructions ==", ""])
        ingredient_names = _extract_ingredient_names(recipe.ingredients or [])

        for step in recipe.instructions:
            step = _extract_timers_from_text(step)
            step = _mark_items_in_text(step, recipe.equipment or [], '#')
            step = _mark_items_in_text(step, ingredient_names, '@')
            lines.extend([step, ""])

    # Notes as > prefix (Cooklang notes syntax)
    if recipe.notes:
        lines.extend(f"> {note}" for note in recipe.notes)
        lines.append("")

    return "\n".join(lines)


def _convert_ingredient_to_cooklang(ingredient: str) -> str:
    """Converts an ingredient string to Cooklang @ingredient{amount%unit}(prep) format.

    Handles various formats:
    - "200g Mehl" -> @Mehl{200%g}
    - "2 EL Öl" -> @Öl{2%EL}
    - "1/2 TL Salz" -> @Salz{1/2%TL}
    - "200-250g Butter" -> @Butter{200-250%g}
    - "1 Zwiebel, fein gehackt" -> @Zwiebel{1}(fein gehackt)
    - "200g Mehl (gesiebt)" -> @Mehl{200%g}(gesiebt)
    - "Salz" -> @Salz{}
    """
    ingredient = ingredient.strip()

    # Security: Limit length to prevent ReDoS attacks
    if len(ingredient) > 200:
        return f"@{ingredient[:50]}...{{}}"
    # Section headers should return Cooklang section syntax
    if ingredient.startswith("## "):
        return f"== {ingredient[3:]} =="

    # Extract preparation hint from parentheses or comma-separated suffix
    prep_hint, clean_ingredient = _extract_prep_hint(ingredient)

    # Parse "amount unit name" pattern (using pre-compiled pattern)
    match = _COOKLANG_INGREDIENT_PATTERN.match(clean_ingredient)

    if match and match.group(3):
        amount = match.group(1).strip().replace(',', '.')
        unit = match.group(2) or ""
        name = match.group(3).strip()
        result = f"@{name}{{{amount}%{unit}}}" if unit else f"@{name}{{{amount}}}"
    else:
        # No amount found - just use ingredient name
        result = f"@{clean_ingredient}{{}}"

    return f"{result}({prep_hint})" if prep_hint else result


def _extract_prep_hint(ingredient: str) -> tuple[str | None, str]:
    """Extracts preparation hint from ingredient string.

    Returns: (prep_hint, clean_ingredient) tuple
    """
    # Pattern 1: "(preparation)" at the end
    paren_match = re.search(r'\s*\(([^)]+)\)\s*$', ingredient)
    if paren_match:
        return paren_match.group(1).strip(), ingredient[:paren_match.start()].strip()

    # Pattern 2: ", preparation" at the end (only if looks like prep instruction)
    comma_match = re.search(r',\s*([^,]+)$', ingredient)
    if comma_match:
        potential_hint = comma_match.group(1).strip()
        # Use pre-compiled pattern for prep words
        if _COOKLANG_PREP_WORDS.search(potential_hint):
            return potential_hint, ingredient[:comma_match.start()].strip()

    return None, ingredient


def format_recipe_markdown(recipe: Recipe) -> str:
    """Formats a recipe as Markdown for Obsidian."""
    lines = []

    # Meta block
    meta_parts = []
    if recipe.source_url:
        source_text = recipe.creator or recipe.source_url.split("/")[2]
        meta_parts.append(f"**Source:** [{source_text}]({recipe.source_url})")
    if recipe.servings:
        meta_parts.append(f"**Servings:** {recipe.servings}")

    # Times
    times = []
    if recipe.prep_time:
        times.append(f"Prep: {recipe.prep_time}")
    if recipe.cook_time:
        times.append(f"Cook: {recipe.cook_time}")
    if recipe.total_time:
        times.append(f"Total: {recipe.total_time}")
    elif not times and (recipe.prep_time or recipe.cook_time):
        pass  # No total time needed if individual times present
    if times:
        meta_parts.append(f"**Time:** {' | '.join(times)}")

    if recipe.difficulty:
        meta_parts.append(f"**Difficulty:** {recipe.difficulty}")

    if recipe.tags:
        tags_str = " ".join(f"#{tag.replace(' ', '-')}" for tag in recipe.tags)
        meta_parts.append(f"**Tags:** {tags_str}")

    lines.extend(meta_parts)
    lines.append("")

    # Ingredients
    lines.append("## Ingredients")
    lines.append("")
    for ingredient in recipe.ingredients:
        if ingredient.startswith("## "):
            lines.append(f"\n### {ingredient[3:]}")
            lines.append("")
        else:
            lines.append(f"- {ingredient}")
    lines.append("")

    # Instructions
    lines.append("## Instructions")
    lines.append("")
    for i, step in enumerate(recipe.instructions, 1):
        lines.append(f"{i}. {step}")
    lines.append("")

    # Equipment (if present)
    if recipe.equipment:
        lines.append("## Equipment")
        lines.append("")
        for item in recipe.equipment:
            lines.append(f"- {item}")
        lines.append("")

    # Tips/Notes (if present)
    if recipe.notes:
        lines.append("## Tips")
        lines.append("")
        for note in recipe.notes:
            lines.append(f"- {note}")
        lines.append("")

    return "\n".join(lines)
