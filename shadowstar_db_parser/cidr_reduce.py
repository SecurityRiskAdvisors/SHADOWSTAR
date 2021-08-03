#!/usr/bin/env python3

'''
Reduces a set of CIDR blocks into the minimal set of CIDR blocks which span the
same logical space as the original set. Example:

input = ['192.168.0.0/24', '192.168.1.0/24', '192.168.0.0/16']
output = ['192.168.0.0/16']

This script assumes that it will be consuming output from the TSV file generated
with the parser.py script.

Suggested usage:
    grep 'keyword' network_info.tsv | python3 cidr_reduce.py
'''

import sys
import fileinput


def ipv4_to_int(row):
    ret = [0]
    parts = row[0].split('/')[0].split('.')
    for i, part in enumerate(parts):
        ret[0] += (int(part) << (24-(8*i)))
    ret.extend(row)
    return ret


def ipv6_to_int(row):
    ret = [0]
    ipv6 = row[0].split('/')[0]
    end_colon = ipv6.endswith('::')
    if ipv6.count(':') != 8:
        repl = ':'.join(['0000'] * (8-ipv6.count(':')))
        ipv6 = ipv6.replace('::', f'{repl}{":" if not end_colon else ""}')
    parts = ipv6.split(':')
    for i, part in enumerate(parts):
        ret[0] += (int(part, 16) << (112-(16*i)))
    ret.extend(row)
    return ret


def ip_to_int(row):
    if row[0].count(':') > 1:
        return ipv6_to_int(row)
    return ipv4_to_int(row)


def mask_to_span(start, mask):
    if start > pow(2,32):
        return pow(2, 128-mask)
    elif mask > 32:
        return pow(2, 128-mask)
    return pow(2, 32-mask)


def main():
    rows = []
    masks = {}

    # Read in data from stdin
    for line in fileinput.input():
        rows.append(line.split('\t'))

    # Convert all CIDR blocks into integers, sort them into ascending order
    augmented_rows = sorted([ip_to_int(row) for row in rows])
    
    # Compute the largest mask (smallest numerical value) for each block
    for row in augmented_rows:
        mask = int(row[1].split('/')[1])
        if not row[0] in masks or masks[row[0]] > mask:
            masks[row[0]] = mask

    # Compute the minimal spanning set of CIDR blocks
    idx, start_idx = 0, 0
    start = augmented_rows[0][0]
    span = mask_to_span(start, masks[start])

    while idx < len(augmented_rows)-1:
        idx += 1
        if start + span <= augmented_rows[idx][0]:
            sys.stdout.write('\t'.join(augmented_rows[start_idx][1:]))
            if idx < len(augmented_rows):
                start_idx = idx
                start = augmented_rows[start_idx][0]
                span = mask_to_span(start, masks[start])

    sys.stdout.write('\t'.join(augmented_rows[start_idx][1:]))


if __name__ == '__main__':
    main()
