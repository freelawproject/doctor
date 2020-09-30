import codecs
import os
import subprocess
import traceback
import uuid
from distutils.spawn import find_executable


def get_audio_binary():
    """Get the path to the installed binary for doing audio conversions

    Ah, Linux. Land where ffmpeg can fork into avconv, where avconv can be the
    correct binary for years and years, and where much later, the fork can be
    merged again and avconv can disappear.

    Yes, the above is what happened, and yes, avconv and ffmpeg are pretty much
    API compatible despite forking and them merging back together. From the
    outside, this appears to be an entirely worthless fork that they embarked
    upon, but what do we know.

    In any case, this program finds whichever one is available and then
    provides it to the user. ffmpeg was the winner of the above history, but we
    stick with avconv as our default because it was the one that was winning
    when we originally wrote our code. One day, we'll want to switch to ffmpeg,
    once avconv is but dust in the bin of history.

    :returns path to the winning binary
    """
    path_to_binary = find_executable("avconv")
    if path_to_binary is None:
        path_to_binary = find_executable("ffmpeg")
        if path_to_binary is None:
            raise Exception(
                "Unable to find avconv or ffmpeg for doing "
                "audio conversions."
            )
    return path_to_binary


def convert_mp3(af_local_path):
    """Convert to MP3

    :param af_local_path:
    :return:
    """
    err = ""
    error_code = 0
    av_path = get_audio_binary()
    tmp_path = os.path.join("/tmp", "audio_" + uuid.uuid4().hex + ".mp3")
    av_command = [
        av_path,
        "-i",
        af_local_path,
        "-ar",
        "22050",  # sample rate (audio samples/s) of 22050Hz
        "-ab",
        "48k",  # constant bit rate (sample resolution) of 48kbps
        tmp_path,
    ]
    try:
        _ = subprocess.check_output(av_command, stderr=subprocess.STDOUT)
        # response.headers["err"] = None
        file_data = codecs.open(tmp_path, "rb").read()
    except subprocess.CalledProcessError as e:
        file_data = ""
        err = "%s failed command: %s\nerror code: %s\noutput: %s\n%s" % (
            av_path,
            av_command,
            e.returncode,
            e.output,
            traceback.format_exc(),
        )
        error_code = 1
    # response.data = file_data
    return file_data, err, error_code
