"""
Benjamin Cecile

Uses FFMpeg to split a music file into individual tracks
By using FFMpeg, any file format that it supports can be split
The saved files will be in a folder with the same name as the original music filename
 Ex. something/music.mp4 (as in the timing file) -> something/music/* (files inside that folder)

With regards to metadata, it will make a best effort for each file
If it's a file format that doesn't support metadata, it will try again without setting metadata
The metadata fields that will be set:
- Title (nameOfSong)
- Artist/Author (artist)
- Album (original music filename)

Format of the timing file:
Music filename to use for input
"|" are used for separators
startTime[|endTime]|nameOfSong[|artist] (the endTime and artist are optional)
... (Use the above format for as many lines as needed)
Any line that starts with "#" will be ignored
* endTime is optional and will use the next line's startTime or the end of the file as the end
  of the current song
* The times are in the format of:
  [[HH:]MM:]SS[.m...]
"""

import argparse
from pathlib import Path
import re
import subprocess

def main():
    """
    The main entrypoint for the program
    """
    #Create a parser to get all of the command line arguments
    parser = argparse.ArgumentParser(description="Split up a music file into individual tracks")
    parser.add_argument("timing_files", type=Path, nargs="+",
                        help="The timing file that describes how a file will be split")
    args = parser.parse_args()

    #Check the existence of FFMpeg on the PATH
    #We also want to silence any output from it
    try:
        result = subprocess.run(["ffmpeg", "--help"], stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        result.check_returncode()
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("FFMpeg needs to be installed on this machine and able to be found on the PATH")
        exit(1)

    #Make a list of tracks, making sure it exists, then using FFMpeg to split the files
    all_tracks = [get_timings(i) for i in args.timing_files if check_good_file(i)]
    for i in all_tracks:
        if isinstance(i, str):
            #Print the error message if the track is actually a string
            print(i)
            continue

        print("Splitting '%s'..." % i["music_file"], end="\r")
        size = len(i["tracks"])
        for (num, track) in enumerate(i["tracks"]):
            track_result = split(i["music_file"], track)
            #Give up on these tracks if we get an error
            if isinstance(track_result, str):
                print(track_result)
                break
            print("Splitting '%s' at track #%d/%d" % (i["music_file"], num, size), end="\r")
        print("Finished splitting '%s' for %d tracks" % (i["music_file"], size))

def check_good_file(file):
    """
    Checks if the given file exists, returning a boolean
    If it doesn't exist, it will print a message saying so
    """
    if not file.exists():
        print("The file '%s' doesn't exist" % file)
        return False
    return True

def get_timings(timing_file):
    """
    Get the timings from the file
    """
    tracks = {"tracks": []}
    with open(timing_file) as reader:
        #Find the music file
        (line, lines) = get_next_line(reader)

        tracks["music_file"] = Path(line)
        if not tracks["music_file"].exists():
            return "The given music file '%s' in '%s' doesn't exist" % (tracks["music_file"],
                                                                        timing_file)
        #Find the tracks
        (line, next_lines) = get_next_line(reader)
        line_num = lines + next_lines
        while line:
            track = parse_track(line)

            #Return the error message, providing context that parse_track doesn't have
            if isinstance(track, str):
                return track % (timing_file, line_num)

            tracks["tracks"].append(track)

            (line, lines) = get_next_line(reader)
            line_num += lines

        #Adjust the end_times if they don't exist
        if len(tracks["tracks"]) > 1:
            for (i, track) in enumerate(tracks["tracks"][:-1]):
                #If we can't find an end_time copy the start time from the next track
                if track["end_time"] is None:
                    track["end_time"] = tracks["tracks"][i + 1]["start_time"]
    return tracks

def get_next_line(reader):
    """
    Gets the next real line by ignoring comments
    The major thing it does is return None if the line is a comment
    """
    line = reader.readline()
    count = 1
    while line and line[0] == "#":
        line = reader.readline()
        count += 1
    #Strip of any whitespace before or after the line (including a newline)
    return (line.strip(), count)

def parse_track(track):
    """
    Tries to parse a track. This is a line from the timing file
    If the parsing fails, it will return an error string that will be subbed with the timing file
     name and the track number
    If the optional parts (end_time and artist) are not there, they will have None instead
    """
    parts = track.split("|")
    if len(parts) < 2:
        return "'%s' at line %d must have a start time and a song name"

    start_time = parse_time(parts[0])
    #Need to explicitly check for False because the time could be 0
    if start_time is False:
        return "'%s' at line %d must follow the correct time syntax in the start time"

    end_time = parse_time(parts[1])
    if end_time is False:
        #Adjust the name_index if the end_time wasn't there
        name_index = 1
        end_time = None
    else:
        name_index = 2

    if name_index >= len(parts):
        return "'%s' at line %d must have a song name"
    song_name = parts[name_index]
    artist = None
    if name_index + 1 < len(parts):
        artist = parts[name_index + 1]

    return {
        "start_time": start_time,
        "end_time": end_time,
        "song_name": song_name,
        "artist": artist
    }

#This regex gets the time with hours, minutes and milliseconds as optional
#Hours, minutes and seconds are all 2 digits
#Milliseconds can any number of digits
TIME_RE = re.compile(r"^(?:(?:(?P<H>\d\d):)?(?P<M>\d\d):)?(?P<S>\d\d)(?:(?:\.)(?P<ms>\d+))?$")
def parse_time(time):
    """
    If the given time is a time, return time in seconds or False
    """
    match = TIME_RE.match(time)
    if not match:
        return False

    seconds = int(match["S"])
    if match["H"]: #Hours
        seconds += int(match["H"]) * 3600
    if match["M"]: #Minutes
        seconds += int(match["M"]) * 60
    if match["ms"]: #Milliseconds
        seconds += int(match["ms"]) / 1000

    return seconds

def split(file, track):
    """
    Splits the given track with FFMpeg from the file
    Returns a string if there was an error, None if not
    """
    #Set the standard run options
    options = ["ffmpeg"]

    #Set the start time of the big music file
    options.append("-ss")
    options.append(str(track["start_time"]))

    #Set the duration by using the end time
    #If there isn't an end time, that means it's the last track and should go to the end of the file
    if track["end_time"] is not None:
        options.append("-t")
        options.append(str(track["end_time"] - track["start_time"]))

    #Set the input file
    options.append("-i")
    options.append(str(file))

    #Make sure to copy the codec
    options.append("-c")
    options.append("copy")

    #Set the force overwrite
    options.append("-y")

    music_dir = (file.parent / file.stem).resolve()
    music_dir.mkdir(exist_ok=True)

    name = track["song_name"]
    if track["artist"]:
        name += " by %s" % track["artist"]

    #Append the file that we want to create
    #It will be inside a directory named the same of the file (without the suffix)
    options.append("%s/%s%s" % (music_dir, name, file.suffix))

    ffmpeg = subprocess.run(options, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if ffmpeg.returncode:
        return "FFMpeg error on track '%s' in '%s'\nStderr:\n%s" % (options[-1], file,
                                                                    ffmpeg.stderr.decode("UTF-8"))
    return None

if __name__ == "__main__":
    main()
