"""Remove the lines present in the line set given on stdin.

Usage: python removelines.py < [line set]

This script removes a sequence of lines from a set of files.
The line set given on stdin takes the form:

# path\to\file
Line to remove
Line2 to remove
Line3 to remove

# path\to\file2
Line to remove
...

For each file indicated by a line beginning with '#', the sequence
of lines that follow will be removed from that file. A blank lines are
only removed if the line immediately preceeding it was also removed.
This makes it possible to remove C-style comments that contain blank
lines."""

import argparse
import const
import glob
import os
import re
import shutil
import stat
from string import Template
import sys
import time
import traceback

def next_deleted(lines_to_delete, index):
    if index < len(lines_to_delete):
        next = lines_to_delete[index]
        index += 1
    else:
        next = None
    return next, index

def process_slash_star_comment(line, start_col):
    ''' Process the rest of a line that has a "/*" comment.

        - line is the line to process
        - start_col is next column number to process. The
          character at that column is in the /* comment.

        Returns:
        - continued_comment is true iff there was an 
          unclosed "/*" comment after processing line.
        - remnant is what is left of the line if the
          /* */ comments are replaced by blank and
          the // comments deleted.
    '''
    next_col = start_col
    remnant = ''
    continued_comment = True
    while next_col < len(line):
        star_slash_col = line.find('*/', next_col)
        if star_slash_col == -1:
            # End of comment not found.
            continued_comment = True
            break
        else:
            # End of leading comment was found. 
            next_col = star_slash_col + 2
            if next_col == len(line):
                # Comment ended at the end of the line.
                continued_comment = False
                break
            else:
                # More after the end of comment.
                # Replace the comment with a blank.
                remnant += ' '
                # Check rest of line.
                slash_slash_col = line.find('//', next_col)
                slash_star_col = line.find('/*', next_col)
                if (slash_slash_col == -1) and (slash_star_col == -1):
                    # Neither kind of comment starter found.
                    continued_comment = False
                    remnant += line[next_col:]
                elif ((slash_star_col != -1) and 
                        ((slash_slash_col == -1) or (slash_star_col < slash_slash_col))):
                    # Found a "/*" that is before any "//", so a new comment starts.
                    if slash_star_col > next_col:
                        # Get intervening characters
                        remnant += line[next_col: slash_star_col]

                    # Skip over the "/*"
                    next_col = slash_star_col + 2

                    # Now loop back up to top.
                else:
                    # If here, then there must be a "//" comment that was found
                    # before any "/*", if any.
                    if slash_slash_col > next_col:
                        # At least one non-comment character seen.
                        remnant += line[next_col: slash_slash_col]
                    continued_comment = False
                    break

    return continued_comment, remnant

def check_comment(line, started_in_comment):
    ''' Update the comment status of a file as it is read

        - line is the line to process
        - started_in_comment is true if the beginning of this
          line is inside an unclosed "/*" comment.

        Returns:
        - has_comment is true if any part of the line was
          in a comment.
        - continued_comment is true iff there was an 
          unclosed "/*" comment after processing line.
        - remnant is what is left of the line if the
          /* */ comments are replaced by blank and
          the // comments deleted.
    '''
    has_comment = started_in_comment
    remnant = ''
    if started_in_comment:
        continued_comment, remnant = process_slash_star_comment(line, 0)
    else:
        # Was not in comment at start of line.
        slash_slash_col = line.find('//')
        slash_star_col = line.find('/*')
        if (slash_slash_col == -1) and (slash_star_col == -1):
            # Neither kind of comment starter found.
            continued_comment = False
            all_in_comment = False
            remnant = line
        elif ((slash_star_col != -1) and 
                ((slash_slash_col == -1) or (slash_star_col < slash_slash_col))):
            # Found a "/*" that is before any "//", so a new comment starts.
            has_comment = True
            if slash_star_col > 0:
                # At least one non-comment character seen.
                remnant = line[0: slash_star_col]
            # Skip over the "/*"
            next_col = slash_star_col + 2
            continued_comment, remnant2 = process_slash_star_comment(line, next_col)
            remnant += remnant2
        else:
            # If here, then there must be a "//" comment that was found
            # before any "/*", if any.
            has_comment = True
            if slash_slash_col > 0:
                # At least one non-comment character seen.
                remnant = line[0: slash_slash_col]
            continued_comment = False

    return has_comment, continued_comment, remnant

def remove_lines(filename, lines_to_delete):
    lines = []
    p, index = next_deleted(lines_to_delete, 0)
    with open(filename, 'r') as f:
        lastWasMatch = False
        started_in_comment = False
        ended_in_comment = False
        for l in f:
            has_comment, ended_in_comment, remnant = check_comment(l.rstrip(), started_in_comment)
            started_in_comment = ended_in_comment
            if has_comment or (l.strip() == ''):
                if p is None:
                    # Nothing left to match.
                    lines.append(l)
                else:
                    # p is the next line to match.
                    if l.rstrip() == p:
                        if not lastWasMatch and p == '':
                            lines.append(l)
                        else:
                            lastWasMatch = True
                            if remnant.strip():
                                lines.append(remnant + "\n")

                        p, index = next_deleted(lines_to_delete, index)
                    else:
                        lastWasMatch = False
                        lines.append(l)

            else:
                # Not involved in comments, so append.
                lines.append(l)
                lastWasMatch = False

    total = len(lines_to_delete)
    remaining = total - index
    if remaining > 0:
        # We have unmatched comments.
        print("{} of {} unmatched comments for file {}".format(remaining, total, filename))
        for i in range(index, total):
            print("    [{}]: {}".format(i, lines_to_delete[i]))

    with open(filename, 'w') as f:
        f.writelines(lines)

def main(argv):
    parser = argparse.ArgumentParser(description='''Remove selected comments                                     '''
                                     )
    required = parser.add_argument_group('required arguments')
    required.add_argument('-f', '--control-path', type=str, required=True, 
                        help='full path to file specifying the comments to remove')
    args, unknown = parser.parse_known_args(argv)
    file_path = args.control_path
    with open(file_path, 'r') as control_file:
        # Skip to first # line.
        while True:
            l = control_file.readline()
            if l == '':
                return

            if l[0] == '#':
                break

        # If here, l is a line with leading #.
        nextfilename = l[1:].strip()

        previous_line = None
        while nextfilename:
            filename = nextfilename
            nextfilename = ''
            lines_to_delete = []
            
            while True:
                l = control_file.readline()
                if (l == '') and (previous_line != None):
                    lines_to_delete.append(previous_line)
                    break

                if l.startswith('# '):
                    nextfilename = l[1:].strip()
                    break

                if previous_line != None:
                    # We only append the previous line if the next line is
                    # not a file-marker line, since the lines before
                    # the file-marker line are always blank.
                    lines_to_delete.append(previous_line)

                previous_line = l.rstrip()

            remove_lines(filename, lines_to_delete)

if __name__ == '__main__':
    main(sys.argv[1:])
    sys.exit(0)
