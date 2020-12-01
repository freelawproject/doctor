import base64
import os
import subprocess
from typing import AnyStr, ByteString, NoReturn, Dict

import eyed3
from eyed3 import id3
from seal_rookery import seals_data, seals_root

root = os.path.dirname(os.path.realpath(__file__))
assets_dir = os.path.join(root, "..", "assets")


def convert_to_mp3(audio_bytes: ByteString, tmp_path: AnyStr) -> NoReturn:
    """Convert audio bytes to mp3 at temporary path

    :param audio_bytes: Audio file bytes sent to BTE
    :param tmp_path: Temporary filepath for output of audioprocess
    :return:
    """
    av_command = [
        "ffmpeg",
        "-i",
        "/dev/stdin",
        "-ar",
        "22050",
        "-ab",
        "48k",
        "-f",
        "mp3",
        tmp_path,
    ]
    ffmpeg_cmd = subprocess.Popen(
        av_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, shell=False
    )
    ffmpeg_cmd.communicate(audio_bytes)


def set_mp3_meta_data(
    audio_data: Dict, mp3_path: AnyStr
) -> eyed3.core.AudioFile:
    """Set the metadata in audio_data to an mp3 at path.

    :param audio_data: The new metadata to embed in the mp3.
    :param mp3_path: The path to the mp3 to be converted.
    :return: Eyed3 audio file object
    """

    # Load the file, delete the old tags and create a new one.
    audio_file = eyed3.load(mp3_path)
    # Undocumented API from eyed3.plugins.classic.ClassicPlugin#handleRemoves
    id3.Tag.remove(
        audio_file.tag.file_info.name,
        id3.ID3_ANY_VERSION,
        preserve_file_time=False,
    )
    audio_file.initTag()
    audio_file.tag.title = best_case_name(audio_data)
    date_argued = audio_data["date_argued"]
    docket_number = audio_data["docket_number"]
    audio_file.tag.album = (
        f"{audio_data['court_full_name']}, {audio_data['date_argued_year']}"
    )
    audio_file.tag.artist = audio_data["court_full_name"]
    audio_file.tag.artist_url = audio_data["court_url"]
    audio_file.tag.audio_source_url = audio_data["download_url"]

    audio_file.tag.comments.set(
        f"Argued: {date_argued}. Docket number: {docket_number}"
    )
    audio_file.tag.genre = "Speech"
    audio_file.tag.publisher = "Free Law Project"
    audio_file.tag.publisher_url = "https://free.law"
    audio_file.tag.recording_date = date_argued

    # Add images to the mp3. If it has a seal, use that for the Front Cover
    # and use the FLP logo for the Publisher Logo. If it lacks a seal, use the
    # Publisher logo for both the front cover and the Publisher logo.
    try:
        has_seal = seals_data[audio_data["court_pk"]]["has_seal"]
    except AttributeError:
        # Unknown court in Seal Rookery.
        has_seal = False
    except KeyError:
        # Unknown court altogether (perhaps a test?)
        has_seal = False

    flp_image_frames = [
        3,  # "Front Cover". Complete list at eyed3/id3/frames.py
        14,  # "Publisher logo".
    ]
    if has_seal:
        with open(
            os.path.join(seals_root, "512", f"{audio_data['court_pk']}.png"),
            "rb",
        ) as f:
            audio_file.tag.images.set(
                3,
                f.read(),
                "image/png",
                "Seal for %s" % audio_data["court_short_name"],
            )
        flp_image_frames.remove(3)

    for frame in flp_image_frames:
        with open(
            os.path.join(
                assets_dir,
                "producer-300x300.png",
            ),
            "rb",
        ) as f:
            audio_file.tag.images.set(
                frame,
                f.read(),
                "image/png",
                "Created for the public domain by Free Law Project",
            )

    audio_file.tag.save()
    return audio_file


def convert_to_base64(tmp_path: AnyStr) -> AnyStr:
    """Convert file base64 and decode it.

    This allows us to safely return the file in json to CL.

    :param tmp_path:
    :return: Audio file encoded in base64 as a string
    """
    with open(tmp_path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def best_case_name(audio_dict: Dict) -> AnyStr:
    """Take an object and return the highest quality case name possible.

    In general, this means returning the fields in an order like:

        - case_name
        - case_name_full
        - case_name_short

    Assumes that the object passed in has all of those attributes.
    """
    if audio_dict["case_name"]:
        return audio_dict["case_name"]
    elif audio_dict["case_name_full"]:
        return audio_dict["case_name_full"]
    else:
        return audio_dict["case_name_short"]
