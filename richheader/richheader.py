#!/usr/bin/env python
# -*- coding: utf-8 -*-

import struct


class RichHeaderException(Exception):
    def __init__(self, message):
        super(RichHeaderException, self).__init__(message)
        self.message = message


class RichHeaderNotFound(RichHeaderException):
    def __init__(self):
        '''A convenient exception to raise if the Rich Header doesn't exist.'''
        super(RichHeaderNotFound, self).__init__("Rich header does not appear to exist")


class RichHeaderNotPE(RichHeaderException):
    pass


class RichHeader(object):

    def __init__(self):
        '''Creates a ParsedRichHeader from the specified PE File.


        This class assists in parsing the Rich Header from PE Files.
        The Rich Header is the section in the PE file following the dos stub but
        preceding the lfa_new header which is inserted by link.exe when building with
        the Microsoft Compilers.  The Rich Heder contains the following:
            marker, checksum, checksum, checksum,
            R_compid_i, R_occurrence_i,
            R_compid_i+1, R_occurrence_i+1, ...
            R_compid_N-1, R_occurrence_N-1, Rich, marker

            marker = checksum XOR 0x536e6144
            R_compid_i is the ith compid XORed with the checksum
            R_occurrence_i is the ith occurrence  XORed with the checksum
            Rich = the text string 'Rich'

        The checksum is the sum of all the PE Header values rotated by their
        offset and the sum of all compids rotated by their occurrence counts.

        @see _validate_checksum code for checksum calculation

        '''
        self.checksum_mask = 0x536e6144  # DanS (actuall SnaD)
        self.rich_text = b'Rich'
        self.pe_start = 0x3c
        self.pe_field_length = 4

    def get_results(self):
        return self.compids.items(), self.valid_checksum

    def parse_path(self, path):
        '''Opens a file and parse it to find the content of the Rich Header.'''
        self.filehandle = open(path, 'rb')
        self._parse()

    def parse_filehandle(self, filehandle):
        '''Takes an open file and parse it to find the content of the Rich Header.'''
        self.filehandle = filehandle
        self._parse()

    def _get_file_header(self):
        '''Locate the body of the data that contains the rich header.
        This will be (roughly) between 0x3c and the beginning of the PE header,
        but the entire thing up to the last checksum will be needed in order to
        verify the header.
            @throws RichHeaderEmptyFile if the file is empty
        '''
        with self.filehandle as f:
            f.seek(self.pe_start)  # start with 0x3c
            data = f.read(self.pe_field_length)

            if data == '':
                # File is empty, bail
                raise RichHeaderNotPE('Not a PE file.')
            end = struct.unpack('<L', data)[0]  # get the value at 0x3c

            f.seek(0)
            # read until that value is reached
            data = f.read(end)
        return data

    def _parse(self):
        ''' Used internally to parse the PE File and extract Rich Header data.
        Initializes self.compids and self.valid_checksum.
            @throws RichHeaderNotFoundException if the file does not contain a rich header
        '''
        self.header = self._get_file_header()

        compid_end_index = self.header.find(self.rich_text)
        if compid_end_index == -1:
            raise RichHeaderNotFound()

        rich_offset = compid_end_index + len(self.rich_text)

        checksum_text = self.header[rich_offset:rich_offset + 4]
        checksum_value = struct.unpack('<L', checksum_text)[0]
        # start marker denotes the beginning of the rich header
        start_marker = struct.pack('<LLLL', checksum_value ^ self.checksum_mask,
                                   checksum_value, checksum_value, checksum_value)[0]

        rich_header_start = self.header.find(start_marker)
        if rich_header_start == -1:
            raise RichHeaderNotFound()

        # move past the marker and 3 checksums
        compid_start_index = rich_header_start + 16

        # A dictionary of compids and their occurrence counts
        self.compids = {}
        for i in range(compid_start_index, compid_end_index, 8):
            compid = struct.unpack('<L', self.header[i:i + 4])[0] ^ checksum_value
            count = struct.unpack('<L', self.header[i + 4:i + 8])[0] ^ checksum_value
            self.compids[compid] = count

        # A value for later reference to see if the checksum was valid
        self.valid_checksum = self._validate_checksum(rich_header_start, checksum_value)

    def _validate_checksum(self, rich_header_start, checksum):
        ''' Compute the checksum value and see if it matches the checksum stored
        in the Rich Header. The checksum is the sum of all the PE Header values
        rotated by their offset and the sum of all compids rotated by their occurrence counts
            @param rich_header_start The offset to marker, checksum, checksum, checksum
            @returns True if the checksum is valid, false otherwise
        '''

        # initialize the checksum offset at which the rich header is located
        self.checksum = rich_header_start

        # add the value from the pe header after rotating the value by its offset in the pe header
        for i in range(0, rich_header_start):
            if self.pe_start <= i <= self.pe_start + self.pe_field_length - 1:
                continue
            if isinstance(self.header[i], int):
                # Python3
                temp = self.header[i]
            else:
                # Python2
                temp = ord(self.header[i])
            self.checksum += ((temp << (i % 32)) | (temp >> (32 - (i % 32))) & 0xff)
            self.checksum &= 0xffffffff

        # add each compid to the checksum after rotating it by its occurrence count
        for k, v in self.compids.items():
            self.checksum += (k << v % 32 | k >> (32 - (v % 32)))
            self.checksum &= 0xffffffff

        return self.checksum == checksum
