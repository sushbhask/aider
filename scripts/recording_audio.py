#!/usr/bin/env python3
"""
Generate TTS audio files for recording commentary using OpenAI's API.
Usage: python scripts/recording_audio.py path/to/recording.md
"""

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv
from treebeardhq import Log

# Load environment variables from .env file
# Load environment variables from .env file
load_dotenv()

# Configuration
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OUTPUT_DIR = "aider/website/assets/audio"
VOICE = "onyx"  # Options: alloy, echo, fable, onyx, nova, shimmer
MP3_BITRATE = "32k"  # Lower bitrate for smaller files


def extract_recording_id(markdown_file):
    """Extract recording ID from the markdown file path."""
    recording_id = Path(markdown_file).stem
    Log.debug("Extracted recording ID from markdown file", markdown_file=markdown_file, recording_id=recording_id)
    return recording_id


def extract_commentary(markdown_file):
    """Extract commentary markers from markdown file."""
    Log.debug("Extracting commentary from markdown file", markdown_file=markdown_file)
    with open(markdown_file, "r") as f:
        content = f.read()

    # Find Commentary section
    commentary_match = re.search(r"## Commentary\s+(.*?)(?=##|\Z)", content, re.DOTALL)
    if not commentary_match:
        Log.warn("No Commentary section found in markdown file", markdown_file=markdown_file)
        return []

    commentary = commentary_match.group(1).strip()

    # Extract timestamp-message pairs
    markers = []
    for line in commentary.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            line = line[2:]  # Remove the list marker
            match = re.match(r"(\d+):(\d+)\s+(.*)", line)
            if match:
                minutes, seconds, message = match.groups()
                time_in_seconds = int(minutes) * 60 + int(seconds)
                markers.append((time_in_seconds, message))

    Log.info("Extracted commentary markers from markdown file", markdown_file=markdown_file, marker_count=len(markers))
    return markers


def check_ffmpeg():
    """Check if FFmpeg is available."""
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        Log.debug("FFmpeg is available")
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        Log.warn("FFmpeg not found")
        return False


def compress_audio(input_file, output_file, bitrate=MP3_BITRATE):
    """Compress audio file using FFmpeg."""
    Log.debug("Compressing audio file", input_file=input_file, output_file=output_file, bitrate=bitrate)
    if not check_ffmpeg():
        Log.warn("Warning: FFmpeg not found, skipping compression")
        return False

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-i",
                input_file,
                "-b:a",
                bitrate,
                "-ac",
                "1",  # Mono audio
                "-y",  # Overwrite output file
                output_file,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        Log.info("Successfully compressed audio file", input_file=input_file, output_file=output_file)
        return True
    except subprocess.SubprocessError as e:
        Log.error("Error compressing audio", error=e, input_file=input_file, output_file=output_file)
        return False


def generate_audio_openai(text, output_file, voice=VOICE, bitrate=MP3_BITRATE):
    """Generate audio using OpenAI TTS API and compress it."""
    Log.debug("Generating audio using OpenAI TTS API", output_file=output_file, voice=voice, text_length=len(text))
    if not OPENAI_API_KEY:
        Log.error("Error: OPENAI_API_KEY environment variable not set")
        return False

    url = "https://api.openai.com/v1/audio/speech"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    data = {"model": "tts-1", "input": text, "voice": voice}

    try:
        Log.debug("Making request to OpenAI TTS API")
        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            Log.debug("Successfully received audio from OpenAI API", status_code=response.status_code)
            # Use a temporary file for the initial audio
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as temp_file:
                temp_path = temp_file.name
                temp_file.write(response.content)

            # Get original file size
            original_size = os.path.getsize(temp_path)
            Log.debug("Original audio file created", temp_path=temp_path, size=original_size)

            # Compress the audio to reduce file size
            success = compress_audio(temp_path, output_file, bitrate)

            # If compression failed or FFmpeg not available, use the original file
            if not success:
                with open(output_file, "wb") as f:
                    f.write(response.content)
                Log.info("Using original uncompressed audio file", output_file=output_file, size=original_size)
            else:
                compressed_size = os.path.getsize(output_file)
                reduction = (1 - compressed_size / original_size) * 100
                Log.info("Successfully compressed audio file", 
                         output_file=output_file,
                         original_size=original_size,
                         compressed_size=compressed_size,
                         reduction_percent=reduction)

            # Clean up the temporary file
            try:
                os.unlink(temp_path)
                Log.debug("Temporary file removed", temp_path=temp_path)
            except OSError as e:
                Log.warn("Failed to remove temporary file", error=e, temp_path=temp_path)

            return True
        else:
            Log.error("Error response from OpenAI API", 
                      status_code=response.status_code, 
                      response_text=response.text,
                      output_file=output_file)
            return False
    except Exception as e:
        Log.error("Exception during API call", error=e, output_file=output_file)
        return False


def load_metadata(output_dir):
    """Load the audio metadata JSON file if it exists."""
    metadata_file = os.path.join(output_dir, "metadata.json")
    Log.debug("Loading metadata", metadata_file=metadata_file)

    if os.path.exists(metadata_file):
        try:
            with open(metadata_file, "r") as f:
                metadata = json.load(f)
                Log.debug("Metadata loaded successfully", entry_count=len(metadata))
                return metadata
        except json.JSONDecodeError as e:
            Log.warn("Could not parse metadata file, will recreate it", error=e, metadata_file=metadata_file)

    Log.debug("No existing metadata found or file couldn't be parsed")
    return {}


def save_metadata(output_dir, metadata):
    """Save the audio metadata to JSON file."""
    metadata_file = os.path.join(output_dir, "metadata.json")
    Log.debug("Saving metadata", metadata_file=metadata_file, entry_count=len(metadata))

    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2)
    
    Log.info("Metadata saved successfully", metadata_file=metadata_file, entry_count=len(metadata))


def get_timestamp_key(time_sec):
    """Generate a consistent timestamp key format for metadata."""
    minutes = time_sec // 60
    seconds = time_sec % 60
    timestamp_key = f"{minutes:02d}-{seconds:02d}"
    Log.debug("Generated timestamp key", time_sec=time_sec, timestamp_key=timestamp_key)
    return timestamp_key


def main():
    Log.info("Starting main function")
    parser = argparse.ArgumentParser(description="Generate TTS audio for recording commentary.")
    parser.add_argument("markdown_file", help="Path to the recording markdown file")
    parser.add_argument("--voice", default=VOICE, help=f"OpenAI voice to use (default: {VOICE})")
    parser.add_argument(
        "--output-dir", default=OUTPUT_DIR, help=f"Output directory (default: {OUTPUT_DIR})"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Print what would be done without generating audio"
    )
    parser.add_argument(
        "--force", action="store_true", help="Force regeneration of all audio files"
    )
    parser.add_argument(
        "--bitrate",
        default=MP3_BITRATE,
        help=f"MP3 bitrate for compression (default: {MP3_BITRATE})",
    )
    parser.add_argument(
        "--compress-only",
        action="store_true",
        help="Only compress existing files without generating new ones",
    )

    args = parser.parse_args()
    Log.debug("Command line arguments parsed", args=args)

    # Use args.voice directly instead of modifying global VOICE
    selected_voice = args.voice
    selected_bitrate = args.bitrate

    # Check if FFmpeg is available for compression
    if not check_ffmpeg() and not args.dry_run:
        Log.warn("FFmpeg not found, compression will be skipped")
        print("Warning: FFmpeg not found. Audio compression will be skipped.")
        print("To enable compression, please install FFmpeg: https://ffmpeg.org/download.html")

    recording_id = extract_recording_id(args.markdown_file)
    Log.info("Processing recording", recording_id=recording_id, markdown_file=args.markdown_file)
    print(f"Processing recording: {recording_id}")

    # Create output directory
    output_dir = os.path.join(args.output_dir, recording_id)
    print(f"Audio directory: {output_dir}")
    if not args.dry_run:
        os.makedirs(output_dir, exist_ok=True)
        Log.debug("Created output directory", output_dir=output_dir)

    # If compress-only flag is set, just compress existing files
    if args.compress_only:
        Log.info("Compressing existing files only", output_dir=output_dir)
        print("Compressing existing files only...")
        metadata = load_metadata(output_dir)
        for timestamp_key in metadata:
            filename = f"{timestamp_key}.mp3"
            file_path = os.path.join(output_dir, filename)

            if os.path.exists(file_path):
                temp_file = f"{file_path}.temp"
                Log.debug("Compressing file", filename=filename, file_path=file_path)
                print(f"Compressing: {filename}")

                if not args.dry_run:
                    success = compress_audio(file_path, temp_file, selected_bitrate)
                    if success:
                        # Get file sizes for reporting
                        original_size = os.path.getsize(file_path)
                        compressed_size = os.path.getsize(temp_file)
                        reduction = (1 - compressed_size / original_size) * 100

                        # Replace original with compressed version
                        os.replace(temp_file, file_path)
                        Log.info("Successfully compressed file", 
                                filename=filename, 
                                original_size=original_size, 
                                compressed_size=compressed_size, 
                                reduction_percentage=reduction)
                        print(
                            f"  ✓ Compressed: {original_size} → {compressed_size} bytes"
                            f" ({reduction:.1f}% reduction)"
                        )
                    else:
                        Log.error("Failed to compress file", filename=filename)
                        print("  ✗ Failed to compress")
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                else:
                    print(f"  Would compress: {file_path}")
        
        Log.info("Compression only process completed", file_count=len(metadata))
        return

    # Extract commentary markers
    markers = extract_commentary(args.markdown_file)

    if not markers:
        Log.warn("No commentary markers found in file", markdown_file=args.markdown_file)
        print("No commentary markers found!")
        return

    Log.info("Found commentary markers", count=len(markers))
    print(f"Found {len(markers)} commentary markers")

    # Load existing metadata
    metadata = load_metadata(output_dir)
    Log.debug("Loaded metadata", entry_count=len(metadata))

    # Create a dictionary of current markers for easier comparison
    current_markers = {}
    for time_sec, message in markers:
        timestamp_key = get_timestamp_key(time_sec)
        current_markers[timestamp_key] = message

    # Track files that need to be deleted (no longer in the markdown)
    files_to_delete = []
    for timestamp_key in metadata:
        if timestamp_key not in current_markers:
            files_to_delete.append(f"{timestamp_key}.mp3")

    # Delete files that are no longer needed
    if files_to_delete and not args.dry_run:
        Log.info("Removing obsolete files", file_count=len(files_to_delete), files=files_to_delete)
        for filename in files_to_delete:
            file_path = os.path.join(output_dir, filename)
            if os.path.exists(file_path):
                print(f"Removing obsolete file: {filename}")
                os.remove(file_path)
    elif files_to_delete:
        Log.debug("Would remove obsolete files (dry run)", file_count=len(files_to_delete), files=files_to_delete)
        print(f"Would remove {len(files_to_delete)} obsolete files: {', '.join(files_to_delete)}")

    # Generate audio for each marker
    files_generated = 0
    files_skipped = 0
    files_failed = 0
    
    for time_sec, message in markers:
        timestamp_key = get_timestamp_key(time_sec)
        filename = f"{timestamp_key}.mp3"
        output_file = os.path.join(output_dir, filename)

        # Check if we need to generate this file
        needs_update = args.force or (
            timestamp_key not in metadata or metadata[timestamp_key] != message
        )

        minutes = time_sec // 60
        seconds = time_sec % 60

        Log.debug("Processing marker", timestamp=f"{minutes}:{seconds:02d}", message=message, needs_update=needs_update)
        print(f"Marker at {minutes}:{seconds:02d} - {message}")

        if not needs_update:
            print("  ✓ Audio file already exists with correct content")
            files_skipped += 1
            continue

        if args.dry_run:
            Log.debug("Would generate audio file (dry run)", output_file=output_file)
            print(f"  Would generate: {output_file}")
        else:
            print(f"  Generating: {output_file}")
            success = generate_audio_openai(
                message, output_file, voice=selected_voice, bitrate=selected_bitrate
            )
            if success:
                Log.info("Successfully generated audio file", 
                         timestamp=f"{minutes}:{seconds:02d}", 
                         output_file=output_file)
                print("  ✓ Generated audio file")
                # Update metadata with the new message
                metadata[timestamp_key] = message
                files_generated += 1
            else:
                Log.error("Failed to generate audio file", 
                          timestamp=f"{minutes}:{seconds:02d}", 
                          output_file=output_file)
                print("  ✗ Failed to generate audio")
                files_failed += 1

    # Save updated metadata
    if not args.dry_run:
        # Remove entries for deleted files
        for timestamp_key in list(metadata.keys()):
            if timestamp_key not in current_markers:
                del metadata[timestamp_key]

        save_metadata(output_dir, metadata)
        Log.info("Metadata saved", entry_count=len(metadata))
    
    Log.info("Audio generation process completed", 
             total_markers=len(markers), 
             files_generated=files_generated, 
             files_skipped=files_skipped, 
             files_failed=files_failed,
             files_deleted=len(files_to_delete) if not args.dry_run and files_to_delete else 0)


if __name__ == "__main__":
    main()
