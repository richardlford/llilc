"""Find C/C++-style comments in the list of files given on stdin.

Usage: python findcomments.py < [list of files] > [comment database]

This script searches each path given on stdin for C/C++-style comments and
outputs the comments it finds in order. The comments for each file are
preceeded by a line containing a single leading '#' and the path to
the file."""

import sys, re

def printIfNot(any, m):
    if not any:
        print(m)
        any = True

    return any

def main(argv):
    lcprog = re.compile(r'//')
    mlsprog = re.compile(r'/\*')
    mleprog = re.compile(r'\*/')

    for l in sys.stdin:
        p = l.strip()
        with open(p, 'r') as f:
            any = False
            st = 0
            for s in f:
                s = s.rstrip()
                if st == 0:
                    if lcprog.search(s) is not None:
                        any = printIfNot(any, '\n# ' + p)
                        print(s)
                    elif mlsprog.search(s) is not None:
                        any = printIfNot(any, '\n# ' + p)
                        print(s)
                        if mleprog.search(s) is not None:
                            st = 0
                        else:
                            st = 1
                else:
                    print(s)
                    if mleprog.search(s) is not None:
                        st = 0

if __name__ == "__main__":
    main(sys.argv[1:])
    sys.exit(0)
