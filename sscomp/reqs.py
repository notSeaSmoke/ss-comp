import vapoursynth as vs

from typing import List, NoReturn, Optional, Type, Dict, BinaryIO, Callable, TextIO
from enum import Enum
from functools import partial
from vstools import InvalidColorFamilyError, get_prop, get_render_progress
from concurrent.futures import Future
from threading import Condition
from requests import Session

import colorama
import pkg_resources
import random
import sys
import traceback

core = vs.core
colorama.init()
RenderCallback = Callable[[int, vs.VideoFrame], None]


class RenderContext:
    """Contains info on the current render operation."""

    clip: vs.VideoNode
    queued: int
    frames: dict[int, vs.VideoFrame]
    frames_rendered: int
    timecodes: list[float]
    condition: Condition

    def __init__(self, clip: vs.VideoNode, queued: int) -> None:
        self.clip = clip
        self.queued = queued
        self.frames = {}
        self.frames_rendered = 0
        self.timecodes = [0.0]
        self.condition = Condition()


class Writer(Enum):
    FFMPEG = 1
    IMWRI = 2


class FileError(Exception):
    ...


class Colours:
    """Colour constants"""
    FAIL_DIM: str = colorama.Back.RED + colorama.Fore.BLACK + colorama.Style.NORMAL
    FAIL_BRIGHT: str = colorama.Back.RED + colorama.Fore.WHITE + colorama.Style.NORMAL
    WARN: str = colorama.Back.YELLOW + colorama.Fore.BLACK + colorama.Style.NORMAL
    INFO: str = colorama.Back.BLUE + colorama.Fore.WHITE + colorama.Style.BRIGHT
    RESET: str = colorama.Style.RESET_ALL
    FAILS: List[str] = [FAIL_DIM, FAIL_BRIGHT]


class Status:
    @staticmethod
    def fail(string: str, /, *, exception: Type[BaseException] = Exception, chain_err: Optional[BaseException] = None) -> NoReturn:
        curr_split: List[str] = []

        # All that stuff is just for alternating colours lmao
        if chain_err:
            class _Exception(BaseException):
                __cause__ = chain_err

            curr = _Exception()

            for p in traceback.format_exception(None, curr, None)[:-1]:
                curr_split.extend(p.splitlines(keepends=True))

        for p in traceback.format_stack()[:-2]:
            curr_split.extend(p.splitlines(keepends=True))

        curr_split.append(f'{exception.__name__}: {string}')

        curr_split = [Colours.FAILS[i % 2] + line + Colours.RESET for i, line in enumerate(curr_split[::-1])][::-1]
        sys.exit(''.join(curr_split) + Colours.RESET)

    @staticmethod
    def warn(string: str, /) -> None:
        print(f'{Colours.WARN}{string}{Colours.RESET}')

    @staticmethod
    def info(string: str, /) -> None:
        print(f'{Colours.INFO}{string}{Colours.RESET}')

    @staticmethod
    def logo() -> None:
        with open(pkg_resources.resource_filename('vardautomation', 'logo.txt'), 'r', encoding='utf-8') as logo:
            print(''.join(Colours.INFO + line + Colours.RESET for line in logo.readlines()), '\n')


def _get_slowpics_header(
    content_length: str, content_type: str, sess: Session
) -> Dict[str, str]:
    return {
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "en-US,en;q=0.5",
        "Content-Length": content_length,
        "Content-Type": content_type,
        "Origin": "https://slow.pics/",
        "Referer": "https://slow.pics/comparison",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "X-XSRF-TOKEN": sess.cookies.get_dict()["XSRF-TOKEN"],
    }


def finish_frame(outfile: BinaryIO | None, timecodes: TextIO | None, ctx: RenderContext) -> None:
    """
    Output a frame.

    :param outfile:   Output IO handle for Y4MPEG.
    :param timecodes: Output IO handle for timecodesv2.
    :param ctx:       Rendering context.
    """
    if timecodes:
        timecodes.write(f"{round(ctx.timecodes[ctx.frames_rendered]*1000):d}\n")
    if outfile is None:
        return

    f = ctx.frames[ctx.frames_rendered]

    outfile.write("FRAME\n".encode("utf-8"))

    f._writelines(outfile.write)


def clip_async_render(clip: vs.VideoNode,
                      outfile: BinaryIO | None = None,
                      timecodes: TextIO | None = None,
                      progress: str | None = "Rendering clip...",
                      callback: RenderCallback | list[RenderCallback] | None = None) -> list[float]:
    """
    Render a clip by requesting frames asynchronously using clip.get_frame_async.

    You must provide a callback with frame number and frame object.

    This is mostly a re-implementation of VideoNode.output, but a little bit slower since it's pure python.
    You only really need this when you want to render a clip while operating on each frame in order
    or you want timecodes without using vspipe.

    :param clip:                        Clip to render.
    :param outfile:                     Y4MPEG render output BinaryIO handle. If None, no Y4M output is performed.
                                        Use :py:func:`sys.stdout.buffer` for stdout. (Default: None)
    :param timecodes:                   Timecode v2 file TextIO handle. If None, timecodes will not be written.
    :param progress:                    String to use for render progress display.
                                        If empty or ``None``, no progress display.
    :param callback:                    Single or list of callbacks to be performed. The callbacks are called.
                                        when each sequential frame is output, not when each frame is done.
                                        Must have signature ``Callable[[int, vs.VideoNode], None]``
                                        See :py:func:`lvsfunc.comparison.diff` for a use case (Default: None).

    :return:                            List of timecodes from rendered clip.

    :raises ValueError:                 Variable format clip is passed.
    :raises InvalidColorFamilyError:    Non-YUV or GRAY clip is passed.
    :raises ValueError:                 "What have you done?"
    """
    cbl = [] if callback is None else callback if isinstance(callback, list) else [callback]

    if progress:
        p = get_render_progress()
        task = p.add_task(progress, total=clip.num_frames)

        def _progress_cb(n: int, f: vs.VideoFrame) -> None:
            p.update(task, advance=1)

        cbl.append(_progress_cb)

    ctx = RenderContext(clip, core.num_threads)

    bad_timecodes: bool = False

    def cb(f: Future[vs.VideoFrame], n: int) -> None:
        ctx.frames[n] = f.result()
        nn = ctx.queued

        while ctx.frames_rendered in ctx.frames:
            nonlocal timecodes
            nonlocal bad_timecodes

            frame = ctx.frames[ctx.frames_rendered]
            # if a frame is missing timing info, clear timecodes because they're worthless
            if ("_DurationNum" not in frame.props or "_DurationDen" not in frame.props) and not bad_timecodes:
                bad_timecodes = True
                if timecodes:
                    timecodes.seek(0)
                    timecodes.truncate()
                    timecodes = None
                ctx.timecodes = []
                print("clip_async_render: frame missing duration information, discarding timecodes")
            elif not bad_timecodes:
                ctx.timecodes.append(ctx.timecodes[-1]
                                     + get_prop(frame, "_DurationNum", int)
                                     / get_prop(frame, "_DurationDen", int))
            finish_frame(outfile, timecodes, ctx)
            [cb(ctx.frames_rendered, ctx.frames[ctx.frames_rendered]) for cb in cbl]
            del ctx.frames[ctx.frames_rendered]  # tfw no infinite memory
            ctx.frames_rendered += 1

        # enqueue a new frame
        if nn < clip.num_frames:
            ctx.queued += 1
            cbp = partial(cb, n=nn)
            clip.get_frame_async(nn).add_done_callback(cbp)  # type: ignore

        ctx.condition.acquire()
        ctx.condition.notify()
        ctx.condition.release()

    if outfile:
        if clip.format is None:
            raise ValueError("clip_async_render: 'Cannot render a variable format clip to y4m!'")

        InvalidColorFamilyError.check(
            clip, (vs.YUV, vs.GRAY), clip_async_render,
            message='Can only render to y4m clips with {correct} color family, not {wrong}!'
        )

        if clip.format.color_family == vs.GRAY:
            y4mformat = "mono"
        else:
            match (clip.format.subsampling_w, clip.format.subsampling_h):
                case (1, 1): y4mformat = "420"
                case (1, 0): y4mformat = "422"
                case (0, 0): y4mformat = "444"
                case (2, 2): y4mformat = "410"
                case (2, 0): y4mformat = "411"
                case (0, 1): y4mformat = "440"
                case _: raise ValueError("clip_async_render: 'What have you done?'")

        y4mformat = f"{y4mformat}p{clip.format.bits_per_sample}" if clip.format.bits_per_sample > 8 else y4mformat

        header = f"YUV4MPEG2 C{y4mformat} W{clip.width} H{clip.height} " \
            f"F{clip.fps.numerator}:{clip.fps.denominator} Ip A0:0\n"
        outfile.write(header.encode("utf-8"))

    if timecodes:
        timecodes.write("# timestamp format v2\n")

    ctx.condition.acquire()

    # seed threads
    if progress:
        p.start()
    try:
        for n in range(min(clip.num_frames, core.num_threads)):
            cbp = partial(cb, n=n)  # lambda won't bind the int immediately
            clip.get_frame_async(n).add_done_callback(cbp)  # type: ignore

        while ctx.frames_rendered != clip.num_frames:
            ctx.condition.wait()
    finally:
        if progress:
            p.stop()

    return ctx.timecodes  # might as well


def lazylist(
    clip: vs.VideoNode,
    dark_frames: int = 8,
    light_frames: int = 4,
    seed: int = 20202020,
    diff_thr: int = 15,
    d_start_thresh: float = 0.075000,  # 0.062745 is solid black
    d_end_thresh: float = 0.380000,
    l_start_thresh: float = 0.450000,
    l_end_thresh: float = 0.750000,
):
    """
    A function for generating a list of frames for comparison purposes.
    Works by running `core.std.PlaneStats()` on the input clip,
    iterating over all frames, and sorting all frames into 2 lists
    based on the PlaneStatsAverage value of the frame.
    Randomly picks frames from both lists, 8 from `dark` and 4
    from `light` by default.

    :param clip:          Input clip
    :param dark_frame:    Number of dark frames
    :param light_frame:   Number of light frames
    :param seed:          seed for `random.sample()`
    :param diff_thr:      Minimum distance between each frames (In seconds)
    :d_start_thresh:      Minimum brightness to be selected as a dark frame
    :d_end_thresh:        Maximum brightness to be selected as a dark frame
    :l_start_thresh:      Minimum brightness to be selected as a light frame
    :l_end_thresh:        Maximum brightness to be selected as a light frame
    :return:              List of dark and light frames
    """

    dark = []
    light = []

    def checkclip(n, f, clip):

        avg = f.props["PlaneStatsAverage"]

        if d_start_thresh <= avg <= d_end_thresh:
            dark.append(n)

        elif l_start_thresh <= avg <= l_end_thresh:
            light.append(n)

        return clip

    s_clip = clip.std.PlaneStats()

    eval_frames = core.std.FrameEval(
        clip, partial(checkclip, clip=s_clip), prop_src=s_clip
    )
    clip_async_render(eval_frames, progress="Evaluating Clip: ")

    dark.sort()
    light.sort()

    dark_dedupe = [dark[0]]
    light_dedupe = [light[0]]

    thr = round(clip.fps_num / clip.fps_den * diff_thr)
    lastvald = dark[0]
    lastvall = light[0]

    for i in range(1, len(dark)):

        checklist = dark[0:i]
        x = dark[i]

        for y in checklist:
            if x >= y + thr and x >= lastvald + thr:
                dark_dedupe.append(x)
                lastvald = x
                break

    for i in range(1, len(light)):

        checklist = light[0:i]
        x = light[i]

        for y in checklist:
            if x >= y + thr and x >= lastvall + thr:
                light_dedupe.append(x)
                lastvall = x
                break

    if len(dark_dedupe) > dark_frames:
        random.seed(seed)
        dark_dedupe = random.sample(dark_dedupe, dark_frames)

    if len(light_dedupe) > light_frames:
        random.seed(seed)
        light_dedupe = random.sample(light_dedupe, light_frames)

    return dark_dedupe + light_dedupe
