import vapoursynth as vs
import os

from typing import List, Dict, Any
from requests import session, post, exceptions
from datetime import datetime

from .reqs import Status, Writer, _get_slowpics_header, lazylist

from vardautomation.types import AnyPath
from vardautomation.vpathlib import VPath
from vardautomation.binary_path import BinaryPath
from vardautomation.tooling import VideoEncoder
from vardefunc.util import select_frames

from requests_toolbelt import MultipartEncoder

core = vs.core


def slowcomp(
    clips: Dict[str, vs.VideoNode],
    refclip: vs.VideoNode,
    folder: AnyPath = "comparison",
    frame_numbers: List = None,
    writer: Writer = Writer.FFMPEG,
    slowpics: bool = False,
    collection_name: str = "",
    public: bool = False,
    webhook: bool = False,
    webhookurl: str = "",
    start: int = 1,
    delim=" ",
):
    """
    Mod of Narkyy's screenshot generator, stolen from awsmfunc.
    Generates screenshots from a list of frames.
    Not specifying `frame_numbers` will use `ssfunc.util.lazylist()` to generate a list of frames.

    :param clips:          Dictionary of clips to compare
    :param refclip:        Reference clip to use for generating list of dark/light frames
    :param folder:            Name of folder where screenshots are saved.
    :param frame_numbers:     List of frames. Can be a list or an external file.
    :param writer:            Writer to use for generating screenshots.
    :param slowpics:          Upload to slowpics.
    :param collection_name:   Name of collection to upload to slowpics.
    :param public:            Make collection public.
    :param webhook:           Send webhook to Discord.
    :param webhookurl:        Discord webhook to post comparisons to.
    :param start:             Frame to start from.
    :param delim:             Delimiter for the external file.

    > Usage: ScreenGen(src, "Screenshots", "a")
             ScreenGen(enc, "Screenshots", "b")
    """

    frame_num_path = "./{name}".format(name=frame_numbers)

    if refclip is None:
        refclip = clips.values(1)

    if isinstance(frame_numbers, str) and os.path.isfile(frame_num_path):
        with open(frame_numbers) as f:
            screens = f.readlines()

        # Keep value before first delim, so that we can parse default detect zones files
        screens = [v.split(delim)[0] for v in screens]

        # str to int
        screens = [int(x.strip()) for x in screens]

    elif isinstance(frame_numbers, list):
        screens = frame_numbers

    elif frame_numbers is None:
        screens = lazylist(refclip)

    else:
        raise TypeError(
            "frame_numbers must be a a list of frames, a file path, or None"
        )

    for name, clip in clips.items():

        folder_path = "{name}/{group}".format(name=folder, group=name)

        if not os.path.isdir(folder_path):
            os.makedirs(folder_path)

        matrix = clip.get_frame(0).props._Matrix

        if matrix == 2:
            matrix = 1

        clip = clip.resize.Bicubic(
            format=vs.RGB24, matrix_in=matrix, dither_type="error_diffusion"
        )

        if writer == 1:
            clip = select_frames(clip, screens)
            clip = clip.std.ShufflePlanes([1, 2, 0], vs.RGB).std.AssumeFPS(
                fpsnum=1, fpsden=1
            )

            path_images = [
                "{path}/{prefix}_{:05d}.png".format(i[0], path=folder_path, prefix=name)
                for i in enumerate(screens)
            ]

            print(path_images)

            outputs: List[str] = []

            for i, path_image in enumerate(path_images):
                outputs += [
                    "-pred",
                    "mixed",
                    "-ss",
                    f"{i}",
                    "-t",
                    "1",
                    f"{path_image}",
                ]

            settings = [
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "rawvideo",
                "-video_size",
                f"{clip.width}x{clip.height}",
                "-pixel_format",
                "gbrp",
                "-framerate",
                str(clip.fps),
                "-i",
                "pipe:",
                *outputs,
            ]

            VideoEncoder(BinaryPath.ffmpeg, settings, progress_update=None).run_enc(
                clip, None, y4m=False
            )

            print("\n")

        else:
            for i, num in enumerate(screens, start=start):

                filename = "{path}/{prefix}_{:05d}.png".format(
                    i, path=folder_path, prefix=name
                )

                print(f"Saving Frame {i}/{len(screens)} from {name}", end="\r")
                core.imwri.Write(
                    clip,
                    "PNG",
                    filename,
                    overwrite=True,
                ).get_frame(num)

    folder = VPath(folder)
    if slowpics:
        all_images = [sorted((folder / name).glob("*.png")) for name in clips.keys()]
        fields: Dict[str, Any] = {
            "collectionName": collection_name,
            "public": str(public).lower(),
            "optimize-images": "true",
        }

        for i, (name, images) in enumerate(
            zip(list(clips.keys()) + (["diff"]), all_images)
        ):
            for j, image in enumerate(images):
                fields[f"comparisons[{j}].name"] = f"{j}".zfill(5)
                fields[f"comparisons[{j}].images[{i}].name"] = name
                fields[f"comparisons[{j}].images[{i}].file"] = (
                    image.name,
                    image.read_bytes(),
                    "image/png",
                )

        sess = session()
        sess.get("https://slow.pics/api/comparison")
        # TODO: yeet this
        files = MultipartEncoder(fields)

        Status.info("Uploading images...\n")
        url = sess.post(
            "https://slow.pics/api/comparison",
            data=files.to_string(),
            headers=_get_slowpics_header(str(files.len), files.content_type, sess),
        )
        sess.close()

        slowpics_url = f"https://slow.pics/c/{url.text}"
        Status.info(f"Slowpics url: {slowpics_url}")

        url_file = folder / "slow.pics.url"
        url_file.write_text(f"[InternetShortcut]\nURL={slowpics_url}", encoding="utf-8")
        Status.info(f"Url file copied to {url_file}")

        if webhook:
            if collection_name == "":
                collection_name = "unknown"
            data = {"username": "slow.pics"}
            author = {
                "name": "Slowpoke Pics",
                "icon_url": "https://slow.pics/icons/apple-icon-120x120-62b1b8f5767f40f08522e36e58b948f4.png",
            }
            data["embeds"] = [
                {
                    "title": f"{collection_name} | Slowpoke Pics",
                    "description": "slowpics Comparison Service",
                    "author": author,
                    "color": int("0x03b2f8", 0),
                    "timestamp": datetime.utcnow().isoformat(),
                    "url": slowpics_url,
                }
            ]
            result = post(webhookurl, json=data)
            try:
                result.raise_for_status()
            except exceptions.HTTPError as err:
                Status.info(f"Failed to deliver payload to webhook\n{err}")
            else:
                Status.info("Webhook payload delivered successfully")
