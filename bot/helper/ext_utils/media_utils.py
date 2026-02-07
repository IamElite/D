import re
from contextlib import suppress
from PIL import Image
from hashlib import md5
from aiofiles.os import remove, path as aiopath, makedirs
import json
from asyncio import (
    create_subprocess_exec,
    gather,
    wait_for,
    sleep,
)
from asyncio.subprocess import PIPE
from os import path as ospath
from re import search as re_search, escape
from time import time
from aioshutil import rmtree
from langcodes import Language

from ... import LOGGER, cpu_no, DOWNLOAD_DIR
from ...core.config_manager import BinConfig
from .bot_utils import cmd_exec, sync_to_async
from .files_utils import get_mime_type, is_archive, is_archive_split
from .status_utils import time_to_seconds

threads = max(1, cpu_no // 2)
cores = ",".join(str(i) for i in range(threads))


def get_md5_hash(up_path):
    md5_hash = md5()
    with open(up_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
        return md5_hash.hexdigest()


async def create_thumb(msg, _id=""):
    if not _id:
        _id = time()
        path = f"{DOWNLOAD_DIR}thumbnails"
    else:
        path = "thumbnails"
    await makedirs(path, exist_ok=True)
    photo_dir = await msg.download()
    output = ospath.join(path, f"{_id}.jpg")
    await sync_to_async(Image.open(photo_dir).convert("RGB").save, output, "JPEG")
    await remove(photo_dir)
    return output


async def get_media_info(path, extra_info=False):
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ]
        )
    except Exception as e:
        LOGGER.error(f"Get Media Info: {e}. Mostly File not found! - File: {path}")
        return (0, "", "", "") if extra_info else (0, None, None)
    if result[0] and result[2] == 0:
        ffresult = eval(result[0])
        fields = ffresult.get("format")
        if fields is None:
            LOGGER.error(f"get_media_info: {result}")
            return (0, "", "", "") if extra_info else (0, None, None)
        duration = round(float(fields.get("duration", 0)))
        if extra_info:
            lang, qual, stitles = "", "", ""
            if (streams := ffresult.get("streams")) and streams[0].get(
                "codec_type"
            ) == "video":
                qual = int(streams[0].get("height"))
                qual = f"{480 if qual <= 480 else 540 if qual <= 540 else 720 if qual <= 720 else 1080 if qual <= 1080 else 2160 if qual <= 2160 else 4320 if qual <= 4320 else 8640}p"
                for stream in streams:
                    if stream.get("codec_type") == "audio" and (
                        lc := stream.get("tags", {}).get("language")
                    ):
                        with suppress(Exception):
                            lc = Language.get(lc).display_name()
                        if lc not in lang:
                            lang += f"{lc}, "
                    if stream.get("codec_type") == "subtitle" and (
                        st := stream.get("tags", {}).get("language")
                    ):
                        with suppress(Exception):
                            st = Language.get(st).display_name()
                        if st not in stitles:
                            stitles += f"{st}, "
            return duration, qual, lang[:-2], stitles[:-2]
        tags = fields.get("tags", {})
        artist = tags.get("artist") or tags.get("ARTIST") or tags.get("Artist")
        title = tags.get("title") or tags.get("TITLE") or tags.get("Title")
        return duration, artist, title
    return (0, "", "", "") if extra_info else (0, None, None)


async def get_document_type(path):
    is_video, is_audio, is_image = False, False, False
    if (
        is_archive(path)
        or is_archive_split(path)
        or re_search(r".+(\.|_)(rar|7z|zip|bin)(\.0*\d+)?$", path)
    ):
        return is_video, is_audio, is_image
    mime_type = await sync_to_async(get_mime_type, path)
    if mime_type.startswith("image"):
        return False, False, True
    try:
        result = await cmd_exec(
            [
                "ffprobe",
                "-hide_banner",
                "-loglevel",
                "error",
                "-print_format",
                "json",
                "-show_streams",
                path,
            ]
        )
        if result[1] and mime_type.startswith("video"):
            is_video = True
    except Exception as e:
        LOGGER.error(f"Get Document Type: {e}. Mostly File not found! - File: {path}")
        if mime_type.startswith("audio"):
            return False, True, False
        if not mime_type.startswith("video") and not mime_type.endswith("octet-stream"):
            return is_video, is_audio, is_image
        if mime_type.startswith("video"):
            is_video = True
        return is_video, is_audio, is_image
    if result[0] and result[2] == 0:
        fields = eval(result[0]).get("streams")
        if fields is None:
            LOGGER.error(f"get_document_type: {result}")
            return is_video, is_audio, is_image
        is_video = False
        for stream in fields:
            if stream.get("codec_type") == "video":
                codec_name = stream.get("codec_name", "").lower()
                if codec_name not in {"mjpeg", "png", "bmp"}:
                    is_video = True
            elif stream.get("codec_type") == "audio":
                is_audio = True
    return is_video, is_audio, is_image


async def get_streams(file):
    """
    Gets media stream information using ffprobe.

    Args:
        file: Path to the media file.

    Returns:
        A list of stream objects (dictionaries) or None if an error occurs
        or no streams are found.
    """
    cmd = [
        "ffprobe",
        "-hide_banner",
        "-loglevel",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        file,
    ]
    process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        LOGGER.error(f"Error getting stream info: {stderr.decode().strip()}")
        return None

    try:
        return json.loads(stdout)["streams"]
    except KeyError:
        LOGGER.error(
            f"No streams found in the ffprobe output: {stdout.decode().strip()}",
        )
        return None


async def take_ss(video_file, ss_nb) -> bool:
    duration = (await get_media_info(video_file))[0]
    if duration != 0:
        dirpath, name = video_file.rsplit("/", 1)
        name, _ = ospath.splitext(name)
        dirpath = f"{dirpath}/{name}_mltbss"
        await makedirs(dirpath, exist_ok=True)
        interval = duration // (ss_nb + 1)
        cap_time = interval
        cmds = []
        for i in range(ss_nb):
            output = f"{dirpath}/SS.{name}_{i:02}.png"
            cmd = [
                "taskset",
                "-c",
                f"{cores}",
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{cap_time}",
                "-i",
                video_file,
                "-q:v",
                "1",
                "-frames:v",
                "1",
                "-threads",
                f"{threads}",
                output,
            ]
            cap_time += interval
            cmds.append(cmd_exec(cmd))
        try:
            resutls = await wait_for(gather(*cmds), timeout=60)
            if resutls[0][2] != 0:
                LOGGER.error(
                    f"Error while creating screenshots from video. Path: {video_file}. stderr: {resutls[0][1]}"
                )
                await rmtree(dirpath, ignore_errors=True)
                return False
        except Exception:
            LOGGER.error(
                f"Error while creating screenshots from video. Path: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
            )
            await rmtree(dirpath, ignore_errors=True)
            return False
        return dirpath
    else:
        LOGGER.error("take_ss: Can't get the duration of video")
        return False


def _format_time(seconds):
    """Format seconds to HH:MM:SS or MM:SS format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _get_grid_size(count, orientation="landscape"):
    """Calculate optimal grid size for given count and orientation"""
    import math
    if orientation == "portrait":
        # Target a total collage aspect ratio closer to 9:16 for portrait
        # For 16:9 screenshots, we want rows to be roughly 3x cols
        cols = max(2, math.ceil(math.sqrt(count * 0.35)))
        rows = math.ceil(count / cols)
    else:
        # Standard landscape look (roughly square or wider)
        cols = math.ceil(math.sqrt(count))
        rows = math.ceil(count / cols)
        if cols * rows < count:
            rows += 1
        if rows > cols:
            rows, cols = cols, rows
    return rows, cols


async def take_ss_collage(video_file, ss_nb, mode="image", orientation="landscape", sst=None) -> str:
    """
    Create a single collage image with all screenshots in a grid layout.
    
    Args:
        video_file: Path to video file
        ss_nb: Number of screenshots to take
        mode: 'image', 'doc', 'title', or 'detailed'
        sst: List of custom timestamps (optional)
    
    Returns:
        Path to collage image or False on error
    """
    from PIL import ImageDraw, ImageFont
    
    def parse_time(time_str):
        if not time_str:
            return 0
        try:
            time_str = str(time_str).strip()
            if ":" in time_str:
                parts = time_str.split(":")
                if len(parts) == 3: # HH:MM:SS
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                elif len(parts) == 2: # MM:SS
                    return int(parts[0]) * 60 + int(parts[1])
            return int(float(time_str))
        except Exception:
            return 0

    duration, artist, title_meta = await get_media_info(video_file)
    if duration == 0:
        LOGGER.error("take_ss_collage: Can't get the duration of video")
        return False
    
    dirpath, name = video_file.rsplit("/", 1)
    name_only, ext = ospath.splitext(name)
    ss_dir = f"{dirpath}/{name_only}_mltbss"
    temp_dir = f"{ss_dir}/temp"
    await makedirs(temp_dir, exist_ok=True)
    
    # Get video info for detailed mode
    vid_width, vid_height, codec, size_str, format_name = 0, 0, "N/A", "N/A", "N/A"
    video_details, audio_details = "N/A", "N/A"
    
    if mode == "detailed":
        try:
            cmd = [
                BinConfig.FFPROBE_NAME, "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", video_file
            ]
            stdout, _, _ = await cmd_exec(cmd)
            probe_data = json.loads(stdout)
            
            format_info = probe_data.get("format", {})
            format_name = format_info.get("format_long_name", "N/A")
            
            streams = probe_data.get("streams", [])
            v_streams = [s for s in streams if s.get("codec_type") == "video"]
            a_streams = [s for s in streams if s.get("codec_type") == "audio"]
            
            if v_streams:
                v = v_streams[0]
                vid_width = v.get("width", 0)
                vid_height = v.get("height", 0)
                codec = v.get("codec_name", "h264")
                video_details = f"{v.get('codec_long_name', 'N/A')} ({codec})"
            
            if a_streams:
                audio_details = ", ".join([f"{idx+1}. {s.get('tags', {}).get('language', 'Undetermined')} ({s.get('codec_name', 'N/A')})" for idx, s in enumerate(a_streams)])
                
        except Exception as e:
            LOGGER.error(f"take_ss_collage ffprobe error: {e}")
            
        try:
            file_size = ospath.getsize(video_file)
            size_str = f"{file_size / 1048576:.2f} MB ({file_size:,} bytes)"
            if file_size >= 1073741824:
                 size_str = f"{file_size / 1073741824:.2f} GB ({file_size:,} bytes)"
        except Exception:
            pass
    
    # Generate screenshots
    timestamps = []
    if sst and isinstance(sst, list):
        for t in sst:
            seconds = parse_time(t)
            if 0 <= seconds <= duration:
                timestamps.append(seconds)
        ss_nb = len(timestamps)
    
    if not timestamps:
        interval = duration // (ss_nb + 1)
        cap_time = interval
        for i in range(ss_nb):
            timestamps.append(cap_time)
            cap_time += interval

    cmds = []
    for i, cap_time in enumerate(timestamps):
        output = f"{temp_dir}/SS_{i:02}.png"
        cmd = [
            "taskset", "-c", f"{cores}",
            BinConfig.FFMPEG_NAME, "-hide_banner", "-loglevel", "error",
            "-ss", f"{cap_time}", "-i", video_file,
            "-q:v", "1", "-frames:v", "1", "-threads", f"{threads}",
            output,
        ]
        cmds.append(cmd_exec(cmd))
    
    try:
        results = await wait_for(gather(*cmds), timeout=120)
        if results[0][2] != 0:
            LOGGER.error(f"Error creating screenshots. Path: {video_file}. stderr: {results[0][1]}")
            await rmtree(ss_dir, ignore_errors=True)
            return False
    except Exception:
        LOGGER.error(f"Error creating screenshots. Path: {video_file}. Error: Timeout!")
        await rmtree(ss_dir, ignore_errors=True)
        return False
    
    # Calculate grid layout
    rows, cols = _get_grid_size(ss_nb, orientation)
    total_cells = rows * cols
    
    # Load first image to get dimensions
    first_img_path = f"{temp_dir}/SS_00.png"
    try:
        with Image.open(first_img_path) as first_img:
            cell_width, cell_height = first_img.size
    except Exception:
        cell_width, cell_height = 640, 360
    
    # Calculate collage dimensions
    padding = max(6, cell_width // 100)
    collage_width = cols * cell_width + (cols + 1) * padding
    header_height = max(200, (collage_width // 1280) * 200) if mode == "detailed" else 0
    collage_height = rows * cell_height + (rows + 1) * padding + header_height
    
    # Create collage canvas (White background for professional borders)
    collage = Image.new("RGB", (collage_width, collage_height), color=(255, 255, 255))
    draw = ImageDraw.Draw(collage)
    
    # Calculate font sizes based on collage width
    large_size = max(24, collage_width // 40)
    small_size = max(18, collage_width // 60)
    time_size = max(18, cell_width // 18)

    # Try to load font with fallback
    def get_font(size, bold=False):
        fonts = ["DejaVuSans-Bold.ttf", "arialbd.ttf", "LiberationSans-Bold.ttf"] if bold else ["DejaVuSans.ttf", "arial.ttf", "LiberationSans-Regular.ttf", "Verdana.ttf"]
        for font_name in fonts:
            try:
                return ImageFont.truetype(font_name, size)
            except Exception:
                continue
        return ImageFont.load_default()

    font_large = get_font(large_size, bold=True)
    font_small = get_font(small_size)
    font_small_bold = get_font(small_size, bold=True)
    font_time = get_font(time_size)
    
    # Draw header content and recalculate height if needed
    if mode == "detailed":
        # Multi-line metadata without manual spacing
        meta_data = [
            ("File", name),
            ("Size", size_str),
            ("Res.", f"{vid_width}x{vid_height}"),
            ("Dur.", f"{_format_time(duration)} ({duration}s)"),
            ("Format", format_name),
            ("Video", video_details),
            ("Audio", audio_details)
        ]
        
        line_height = small_size + (small_size // 2)
        top_padding = 20
        required_height = top_padding + (len(meta_data) * line_height) + 20
        
        # Adjust collage height if header needs more space
        if required_height > header_height:
            diff = required_height - header_height
            header_height = required_height
            collage_height += diff
            collage = Image.new("RGB", (collage_width, collage_height), color=(255, 255, 255))
            draw = ImageDraw.Draw(collage)

        current_y = top_padding
        left_margin = 30
        
        # Fixed alignment positions (calculated more robustly)
        label_x = left_margin
        # Measure all labels to find maximum width for perfect colon alignment
        all_labels = [l for l, _ in meta_data]
        max_label_w = max([draw.textbbox((0, 0), l, font=font_small_bold)[2] for l in all_labels])
        
        colon_x = label_x + max_label_w + 20
        value_x = colon_x + 40
        
        for label, value in meta_data:
            draw.text((label_x, current_y), label, fill=(0, 0, 0), font=font_small_bold)
            draw.text((colon_x, current_y), ":", fill=(0, 0, 0), font=font_small_bold)
            draw.text((value_x, current_y), str(value), fill=(30, 30, 30), font=font_small)
            current_y += line_height
    
    # Paste screenshots into grid
    for idx in range(total_cells):
        row = idx // cols
        col = idx % cols
        x = padding + col * (cell_width + padding)
        y = header_height + padding + row * (cell_height + padding)
        
        if idx < ss_nb:
            # Paste actual screenshot
            img_path = f"{temp_dir}/SS_{idx:02}.png"
            try:
                with Image.open(img_path) as img:
                    if img.size != (cell_width, cell_height):
                        img = img.resize((cell_width, cell_height), Image.Resampling.LANCZOS)
                    collage.paste(img, (x, y))
                    
                    # Add timeline overlay for title/detailed modes
                    if mode in ("title", "detailed"):
                        time_text = _format_time(timestamps[idx])
                        _, _, tw, th = draw.textbbox((0, 0), time_text, font=font_time)
                        
                        # Sleek semi-transparent background box
                        box_padding_h = 10
                        box_padding_v = 6
                        bw, bh = tw + 2 * box_padding_h, th + 2 * box_padding_v
                        
                        # Position box at TOP-right of cell for best visibility (Pro look)
                        bx = x + cell_width - bw - 15
                        by = y + 15
                        
                        overlay = Image.new('RGBA', (bw, bh), (0, 0, 0, 210))
                        collage.paste(overlay, (bx, by), overlay)
                        
                        # Center text in box
                        text_x = bx + box_padding_h
                        text_y = by + box_padding_v - 2 # Minor adjustment for better centering
                        draw.text((text_x, text_y), time_text, fill=(255, 255, 255), font=font_time)
            except Exception as e:
                LOGGER.error(f"Error pasting screenshot {idx}: {e}")
                draw.rectangle([x, y, x + cell_width, y + cell_height], fill=(245, 245, 245))
                draw.text((x + 10, y + 10), "Error", fill=(200, 50, 50), font=font_large)
        else:
            # Empty cell - draw "No Image" text with refined style
            draw.rectangle([x, y, x + cell_width, y + cell_height], fill=(245, 245, 245), outline=(220, 220, 220))
            no_img_text = "No Image"
            _, _, ntw, nth = draw.textbbox((0, 0), no_img_text, font=font_large)
            tx = x + (cell_width - ntw) // 2
            ty = y + (cell_height - nth) // 2
            draw.text((tx, ty), no_img_text, fill=(180, 180, 180), font=font_large)
    
    # Scale down if too large for Telegram (max ~4000px)
    # The PhotoSaveFileInvalid error is usually due to dimensions exceeding 4000px
    max_dim = 3840
    if collage_width > max_dim or collage_height > max_dim:
        ratio = min(max_dim / collage_width, max_dim / collage_height)
        new_size = (int(collage_width * ratio), int(collage_height * ratio))
        collage = collage.resize(new_size, Image.Resampling.LANCZOS)
        LOGGER.info(f"Collage scaled down to {new_size[0]}x{new_size[1]} for Telegram compatibility")

    # Save collage
    collage_path = f"{ss_dir}/SS.{name_only}_collage.png"
    collage.save(collage_path, "PNG", quality=95)
    
    # Clean up temp directory
    await rmtree(temp_dir, ignore_errors=True)
    
    LOGGER.info(f"Collage created: {collage_path} ({rows}x{cols} grid, {ss_nb} screenshots)")
    return ss_dir


# Legacy functions for backward compatibility
async def take_ss(video_file, ss_nb, orientation="landscape", sst=None) -> bool:
    """Create screenshots collage (backward compatible wrapper)"""
    return await take_ss_collage(video_file, ss_nb, mode="image", orientation=orientation, sst=sst)


async def take_ss_with_title(video_file, ss_nb, orientation="landscape", sst=None) -> bool:
    """Create screenshots collage with timeline overlay"""
    return await take_ss_collage(video_file, ss_nb, mode="title", orientation=orientation, sst=sst)


async def take_ss_detailed(video_file, ss_nb, orientation="landscape", sst=None) -> bool:
    """Create screenshots collage with media info header and timeline"""
    return await take_ss_collage(video_file, ss_nb, mode="detailed", orientation=orientation, sst=sst)


async def get_audio_thumbnail(audio_file):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        audio_file,
        "-an",
        "-vcodec",
        "copy",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while extracting thumbnail from audio. Name: {audio_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while extracting thumbnail from audio. Name: {audio_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    return output


async def get_video_thumbnail(video_file, duration):
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    if duration is None:
        duration = (await get_media_info(video_file))[0]
    if duration == 0:
        duration = 3
    duration = duration // 2
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{duration}",
        "-i",
        video_file,
        "-vf",
        "thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while extracting thumbnail from video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while extracting thumbnail from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    return output


async def get_multiple_frames_thumbnail(video_file, layout, keep_screenshots):
    layout = re.sub(r"(\d+)\D+(\d+)", r"\1x\2", layout)
    ss_nb = layout.split("x")
    if len(ss_nb) != 2 or not ss_nb[0].isdigit() or not ss_nb[1].isdigit():
        LOGGER.error(f"Invalid layout value: {layout}")
        return None
    ss_nb = int(ss_nb[0]) * int(ss_nb[1])
    if ss_nb == 0:
        LOGGER.error(f"Invalid layout value: {layout}")
        return None
    dirpath = await take_ss(video_file, ss_nb)
    if not dirpath:
        return None
    output_dir = f"{DOWNLOAD_DIR}thumbnails"
    await makedirs(output_dir, exist_ok=True)
    output = ospath.join(output_dir, f"{time()}.jpg")
    cmd = [
        "taskset",
        "-c",
        f"{cores}",
        BinConfig.FFMPEG_NAME,
        "-hide_banner",
        "-loglevel",
        "error",
        "-pattern_type",
        "glob",
        "-i",
        f"{escape(dirpath)}/*.png",
        "-vf",
        f"tile={layout}, thumbnail",
        "-q:v",
        "1",
        "-frames:v",
        "1",
        "-f",
        "mjpeg",
        "-threads",
        f"{threads}",
        output,
    ]
    try:
        _, err, code = await wait_for(cmd_exec(cmd), timeout=60)
        if code != 0 or not await aiopath.exists(output):
            LOGGER.error(
                f"Error while combining thumbnails for video. Name: {video_file} stderr: {err}"
            )
            return None
    except Exception:
        LOGGER.error(
            f"Error while combining thumbnails from video. Name: {video_file}. Error: Timeout some issues with ffmpeg with specific arch!"
        )
        return None
    finally:
        if not keep_screenshots:
            await rmtree(dirpath, ignore_errors=True)
    return output


class FFMpeg:
    def __init__(self, listener):
        self._listener = listener
        self._processed_bytes = 0
        self._last_processed_bytes = 0
        self._processed_time = 0
        self._last_processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._total_time = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._start_time = 0

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def speed_raw(self):
        return self._speed_raw

    @property
    def progress_raw(self):
        return self._progress_raw

    @property
    def eta_raw(self):
        return self._eta_raw

    def clear(self):
        self._start_time = time()
        self._processed_bytes = 0
        self._processed_time = 0
        self._speed_raw = 0
        self._progress_raw = 0
        self._eta_raw = 0
        self._time_rate = 0.1
        self._last_processed_time = 0
        self._last_processed_bytes = 0

    async def _ffmpeg_progress(self):
        while not (
            self._listener.subproc.returncode is not None
            or self._listener.is_cancelled
            or self._listener.subproc.stdout.at_eof()
        ):
            try:
                line = await wait_for(self._listener.subproc.stdout.readline(), 60)
            except Exception:
                break
            line = line.decode().strip()
            if not line:
                break
            if "=" in line:
                key, value = line.split("=", 1)
                if value != "N/A":
                    if key == "total_size":
                        self._processed_bytes = int(value) + self._last_processed_bytes
                        self._speed_raw = self._processed_bytes / (
                            time() - self._start_time
                        )
                    elif key == "speed":
                        self._time_rate = max(0.1, float(value.strip("x")))
                    elif key == "out_time":
                        self._processed_time = (
                            time_to_seconds(value) + self._last_processed_time
                        )
                        try:
                            self._progress_raw = (
                                self._processed_time * 100
                            ) / self._total_time
                            if (
                                hasattr(self._listener, "subsize")
                                and self._listener.subsize
                                and self._progress_raw > 0
                            ):
                                self._processed_bytes = int(
                                    self._listener.subsize * (self._progress_raw / 100)
                                )
                            if (time() - self._start_time) > 0:
                                self._speed_raw = self._processed_bytes / (
                                    time() - self._start_time
                                )
                            else:
                                self._speed_raw = 0
                            self._eta_raw = (
                                self._total_time - self._processed_time
                            ) / self._time_rate
                        except ZeroDivisionError:
                            self._progress_raw = 0
                            self._eta_raw = 0
            await sleep(0.05)

    async def ffmpeg_cmds(self, ffmpeg, f_path):
        self.clear()
        self._total_time = (await get_media_info(f_path))[0]
        base_name, ext = ospath.splitext(f_path)
        dir, base_name = base_name.rsplit("/", 1)
        indices = [
            index
            for index, item in enumerate(ffmpeg)
            if item.startswith("mltb") or item == "mltb"
        ]
        outputs = []
        for index in indices:
            output_file = ffmpeg[index]
            if output_file != "mltb" and output_file.startswith("mltb"):
                bo, oext = ospath.splitext(output_file)
                if oext:
                    if ext == oext:
                        prefix = f"ffmpeg{index}." if bo == "mltb" else ""
                    else:
                        prefix = ""
                    ext = ""
                else:
                    prefix = ""
            else:
                prefix = f"ffmpeg{index}."
            output = f"{dir}/{prefix}{output_file.replace('mltb', base_name)}{ext}"
            outputs.append(output)
            ffmpeg[index] = output
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *ffmpeg, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return outputs
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while running ffmpeg cmd, mostly file requires different/specific arguments. Path: {f_path}"
            )
            for op in outputs:
                if await aiopath.exists(op):
                    await remove(op)
            return False

    async def convert_video(self, video_file, ext, retry=False):
        self.clear()
        self._total_time = (await get_media_info(video_file))[0]
        base_name = ospath.splitext(video_file)[0]
        output = f"{base_name}.{ext}"
        if retry:
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-threads",
                f"{threads}",
                output,
            ]
            if ext == "mp4":
                cmd[14:14] = ["-c:s", "mov_text"]
            elif ext == "mkv":
                cmd[14:14] = ["-c:s", "ass"]
            else:
                cmd[14:14] = ["-c:s", "copy"]
        else:
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-i",
                video_file,
                "-map",
                "0",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                output,
            ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            if await aiopath.exists(output):
                await remove(output)
            if not retry:
                return await self.convert_video(video_file, ext, True)
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting video, mostly file need specific codec. Path: {video_file}"
            )
        return False

    async def convert_audio(self, audio_file, ext):
        self.clear()
        self._total_time = (await get_media_info(audio_file))[0]
        base_name = ospath.splitext(audio_file)[0]
        output = f"{base_name}.{ext}"
        cmd = [
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            audio_file,
            "-threads",
            f"{threads}",
            output,
        ]
        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == 0:
            return output
        elif code == -9:
            self._listener.is_cancelled = True
            return False
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while converting audio, mostly file need specific codec. Path: {audio_file}"
            )
            if await aiopath.exists(output):
                await remove(output)
        return False

    async def sample_video(self, video_file, sample_duration, part_duration):
        self.clear()
        self._total_time = sample_duration
        dir, name = video_file.rsplit("/", 1)
        output_file = f"{dir}/SAMPLE.{name}"
        segments = [(0, part_duration)]
        duration = (await get_media_info(video_file))[0]
        remaining_duration = duration - (part_duration * 2)
        parts = (sample_duration - (part_duration * 2)) // part_duration
        time_interval = remaining_duration // parts
        next_segment = time_interval
        for _ in range(parts):
            segments.append((next_segment, next_segment + part_duration))
            next_segment += time_interval
        segments.append((duration - part_duration, duration))

        filter_complex = ""
        for i, (start, end) in enumerate(segments):
            filter_complex += (
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]; "
            )
            filter_complex += (
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]; "
            )

        for i in range(len(segments)):
            filter_complex += f"[v{i}][a{i}]"

        filter_complex += f"concat=n={len(segments)}:v=1:a=1[vout][aout]"

        cmd = [
            BinConfig.FFMPEG_NAME,
            "-hide_banner",
            "-loglevel",
            "error",
            "-progress",
            "pipe:1",
            "-i",
            video_file,
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-threads",
            f"{threads}",
            output_file,
        ]

        if self._listener.is_cancelled:
            return False
        self._listener.subproc = await create_subprocess_exec(
            *cmd, stdout=PIPE, stderr=PIPE
        )
        await self._ffmpeg_progress()
        _, stderr = await self._listener.subproc.communicate()
        code = self._listener.subproc.returncode
        if self._listener.is_cancelled:
            return False
        if code == -9:
            self._listener.is_cancelled = True
            return False
        elif code == 0:
            return output_file
        else:
            try:
                stderr = stderr.decode().strip()
            except Exception:
                stderr = "Unable to decode the error!"
            LOGGER.error(
                f"{stderr}. Something went wrong while creating sample video, mostly file is corrupted. Path: {video_file}"
            )
            if await aiopath.exists(output_file):
                await remove(output_file)
            return False

    async def split(self, f_path, file_, parts, split_size):
        self.clear()
        multi_streams = True
        self._total_time = duration = (await get_media_info(f_path))[0]
        base_name, extension = ospath.splitext(file_)
        split_size -= 3000000
        start_time = 0
        i = 1
        while i <= parts or start_time < duration - 4:
            out_path = f_path.replace(file_, f"{base_name}.part{i:03}{extension}")
            cmd = [
                BinConfig.FFMPEG_NAME,
                "-hide_banner",
                "-loglevel",
                "error",
                "-progress",
                "pipe:1",
                "-ss",
                str(start_time),
                "-i",
                f_path,
                "-fs",
                str(split_size),
                "-map",
                "0",
                "-map_chapters",
                "-1",
                "-async",
                "1",
                "-strict",
                "-2",
                "-c",
                "copy",
                "-threads",
                f"{threads}",
                out_path,
            ]
            if not multi_streams:
                del cmd[12]
                del cmd[12]
            if self._listener.is_cancelled:
                return False
            self._listener.subproc = await create_subprocess_exec(
                *cmd, stdout=PIPE, stderr=PIPE
            )
            await self._ffmpeg_progress()
            _, stderr = await self._listener.subproc.communicate()
            code = self._listener.subproc.returncode
            if self._listener.is_cancelled:
                return False
            if code == -9:
                self._listener.is_cancelled = True
                return False
            elif code != 0:
                try:
                    stderr = stderr.decode().strip()
                except Exception:
                    stderr = "Unable to decode the error!"
                with suppress(Exception):
                    await remove(out_path)
                if multi_streams:
                    LOGGER.warning(
                        f"{stderr}. Retrying without map, -map 0 not working in all situations. Path: {f_path}"
                    )
                    multi_streams = False
                    continue
                else:
                    LOGGER.warning(
                        f"{stderr}. Unable to split this video, if it's size less than {self._listener.max_split_size} will be uploaded as it is. Path: {f_path}"
                    )
                return False
            out_size = await aiopath.getsize(out_path)
            if out_size > self._listener.max_split_size:
                split_size -= (out_size - self._listener.max_split_size) + 5000000
                LOGGER.warning(
                    f"Part size is {out_size}. Trying again with lower split size!. Path: {f_path}"
                )
                await remove(out_path)
                continue
            lpd = (await get_media_info(out_path))[0]
            if lpd == 0:
                LOGGER.error(
                    f"Something went wrong while splitting, mostly file is corrupted. Path: {f_path}"
                )
                break
            elif duration == lpd:
                LOGGER.warning(
                    f"This file has been splitted with default stream and audio, so you will only see one part with less size from orginal one because it doesn't have all streams and audios. This happens mostly with MKV videos. Path: {f_path}"
                )
                break
            elif lpd <= 3:
                await remove(out_path)
                break
            self._last_processed_time += lpd
            self._last_processed_bytes += out_size
            start_time += lpd - 3
            i += 1
        return True
