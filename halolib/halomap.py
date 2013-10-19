# Copyright (c) 2013, Chad Zawistowski
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright
#       notice, this list of conditions and the following disclaimer in the
#       documentation and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER BE LIABLE FOR ANY
# DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""halomap.py

Defines the HaloMap class, as well as functions for loading maps location disk or memory.
"""
import re
from halolib.haloaccess import access_over_file, access_over_memory
from halolib.halostruct import plugin_classes, load_plugins
from halolib.halotag import HaloTag

class HaloMap(object):
    def __init__(self, file=None):
        self.file = file

    def init(self, map_header, index_header, taglist, map_magic, file=None):
        self.map_header = map_header
        self.index_header = index_header
        self.map_magic = map_magic
        self.file = file
        self.tags = {tag.ident: tag for tag in taglist}

    def __str__(self):
        return '[map_header]%s\n[index_header]%s' % (str(self.map_header), str(self.index_header))

    def __repr__(self):
        answer = str(self)
        answer += '\nTag Index:\n'
        for each in self.get_tags():
            answer += str(each) + '\n'
        return answer

    def get_tag(self, first_class='', *name_fragments):
        return next(self.get_tags(first_class, *name_fragments))
    
    def get_tags(self, first_class='', *name_fragments):
        for tag in self.tags.values():
            if first_class == '' or re.search(first_class, tag.first_class):
                if all((regex == '' or re.search(regex, tag.name)) for regex in name_fragments):
                    yield tag
    
    def close(self):
        if self.file != None:
            self.file.close()
            self.file = None

class HaloOffsets(object):
    def __init__(self, location):
        if location == 'file':
            # map_offsets known ahead of time
            self.MapHeader = 0

            # map_offsets determined at runtime
            self.IndexHeader = None
            self.Index = None

        elif location == 'mem':
            # map_offsets known ahead of time
            self.MapHeader = 0x6A8154
            self.IndexHeader = 0x40440000
            self.Executable = 0x400000
            self.WMKillHandler = self.Executable + 0x142538

            # map_offsets determined at runtime
            self.Index = None

        else:
            raise Exception("Bad argument, cannot load Halo from '%s'" % location)

def load_map_common(*, location, map_path=None):
    map_offsets = HaloOffsets(location)

    if location == 'file':
        f = open(map_path, 'r+b')
        ByteAccess = access_over_file(f)
        halomap = HaloMap(f)

    elif location == 'mem':
        ByteAccess = access_over_memory()
        halomap = HaloMap()

        # Force Halo to render video even when window is deselected
        if True: #if fix_video_render:
            ByteAccess(map_offsets.WMKillHandler, 4).write_bytes(b'\xe9\x91\x00\x00', 0)

    else:
        raise Exception("Bad argument, cannot load Halo from '%s'" % location)

    # ensure plugins are loaded
    if len(plugin_classes) == 0:
        load_plugins()

    MapHeader = plugin_classes['map_header']
    IndexHeader = plugin_classes['index_header']
    IndexEntry = plugin_classes['index_entry']

    if location == 'mem':
        # these are some runtime-only structures that may be interesting to edit in the future
        pass
        #ObjectTable = plugin_classes['object_table']
        #PlayerTable = plugin_classes['player_table']

        #object_table = ObjectTable(HaloMemAccess(0x400506B4, 64), 0, halomap)
        #print(object_table)
        
        #player_table = HaloMemAccess(0x402AAF94, 64)
        #print(player_table.read_all_bytes())

    map_header = MapHeader(
                    ByteAccess(
                        map_offsets.MapHeader,
                        MapHeader.struct_size),
                    0,
                    halomap)

    if location == 'file':
        map_offsets.IndexHeader = map_header.index_offset

    index_header = IndexHeader(
                    ByteAccess(
                        map_offsets.IndexHeader,
                        IndexHeader.struct_size),
                    0,
                    halomap)

    if location == 'file':
        # Usually the tag index directly follows the index header. However,
        # some forms of map protection move the tag index to other locations.
        map_offsets.Index = map_header.index_offset + index_header.primary_magic - 0x40440000

        # On disk, we need to use a magic value to convert pointers into file offsets.
        # The magic value is based on the index location.
        map_magic = index_header.primary_magic - map_offsets.Index

    elif location == 'mem':
        # Almost always 0x40440000, unless the map has been 
        map_offsets.Index = index_header.primary_magic

        # In memory, offsets are just raw pointers and require no adjustment.
        map_magic = 0

    index_entries = [IndexEntry(
                        ByteAccess(
                            IndexEntry.struct_size * i + map_offsets.Index,
                            IndexEntry.struct_size),
                        map_magic,
                        halomap) for i in range(index_header.tag_count)]

    meta_offsets = sorted(index_entry.meta_offset_raw for index_entry in index_entries)

    if location == 'file':
        # the BSP's meta has an offset of 0, skip it
        bsp_offset = meta_offsets.pop(0)

    elif location == 'mem':
        # the BSP's meta has a very large, distant offset, skip it
        bsp_offset = meta_offsets.pop()
    

    # to calculate sizes, we need the offset to the end
    meta_offsets.append(meta_offsets[0] + map_header.metadata_size)

    # [00, 10, 40, 55, 80] location offsets,
    #   [10, 30, 15, 25]   calculate sizes...
    #                      but instead of an ordered list, key based on the start offset
    meta_sizes = {start: (end - start) for start, end in zip(meta_offsets[:-1], meta_offsets[1:])}

    # Just give BSP's meta a size of zero for now
    meta_sizes.update({bsp_offset: 0})

    tags = [HaloTag(
                index_entry,
                ByteAccess(
                    index_entry.name_offset_raw - map_magic,
                    256),
                ByteAccess(
                    index_entry.meta_offset_raw - map_magic,
                    meta_sizes[index_entry.meta_offset_raw]),
                map_magic,
                halomap) for index_entry in index_entries]

    halomap.init(map_header, index_header, tags, map_magic)
    return halomap

def load_map(map_path=None):
    if map_path != None:
        return load_map_common(location='file', map_path=map_path)
    else:
        return load_map_common(location='mem')
