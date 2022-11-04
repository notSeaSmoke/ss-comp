# ss-comp
</br>
<p align='center'>
<a href="https://github.com/psf/black"><img alt="Code style: black" src="https://img.shields.io/badge/code%20style-black-000000.svg"></a>
<a href=><img alt="Python: 3.10" src="https://img.shields.io/badge/python-3.10-blue.svg"></a>
<a href="https://github.com/notSeaSmoke/ss-comp/blob/master/LICENSE.md"><img alt="License: MIT" src="https://black.readthedocs.io/en/stable/_static/license.svg"></a>
<a href="https://discord.gg/rFwHDKHfJr"><img alt="Discord" src="https://img.shields.io/discord/771790175591333909?label=discord"></a>
</p>

Modified version of Narkyy's screenshot generator for creating [slowpics](http://slow.pics/) comparisons. Uses `lazylist` for dark scene detection.

## Installation
Simply run

```
python -m pip install git+https://github.com/notSeaSmoke/ss-comp.git && pip uninstall vardautomation  && python -m pip install 'git+https://github.com/Ichunjo/vardautomation.git' -U && pip uninstall lvsfunc && pip install 'git+https://github.com/Setsugennoao/lvsfunc.git@update-vs-packages'
```

Requires Python 3.10

vardautomation currently has dependancy conflicts with some vs-* packages in the release version, hence it's installed from the git. lvsfunc is also broken, setsu's fork is used instead.

## Usage

The upload script uses 2 major fuctions, `lazylist()` and `slowcomp()`.

### lazylist

lazylist uses the `PlaneStatsAverage` value of each frame to determine if it is a dark frame or not. All frames are sorted into 2 lists, from which a specified number of frames are selected randomly.

    clip:               Input clip
    dark_frame:         Number of dark frames. Default 8
    light_frame:        Number of light frames. Default 4
    seed:               seed for `random.sample()`. Default 20202020
    diff_thr:           Minimum distance between each frames (In seconds). Default 15
    d_start_thresh:     Minimum brightness to be selected as a dark frame. Default 0.075000
    d_end_thresh:       Maximum brightness to be selected as a dark frame. Default 0.380000
    l_start_thresh:     Minimum brightness to be selected as a light frame. Default 0.450000
    l_end_thresh:       Maximum brightness to be selected as a light frame. Default 0.750000
    return:             List of dark and light frames

### slowcomp

slowcomp is a modified version of Narkyy's `ScreenGen` from `awsmfunc`. It uses take a Dict of clips, generates screenshots using a specified list of frames (in the form of a List, or an external file), and then uploads it to slow.pics if required. If a list of frames is not specified, it will generate a new list using `lazylist` on the refclip, or the first clip in `clips`.

If a discord webhook is supplied, it will post the comparison to discord using the webhook.

    clips:              Dictionary of clips to compare.
    refclip:            Reference clip to use for generating list of dark/light frames.
    folder:             Name of folder where screenshots are saved. Default "comparison"
    frame_numbers:      List of frames. Can be a list or an external file. Default None
    writer:             Writer to use for generating screenshots. Default Writer.FFMPEG
    slowpics:           Upload to slowpics. Default False
    collection_name:    Name of collection to upload to slowpics.
    public:             Make collection public. Default False
    webhook:            Send webhook to Discord. Default False
    webhookurl:         Discord webhook to post comparisons to.
    start:              Frame to start from. Default 1
    delim:              Delimiter for the external file.
