# Copyright (c) 2013, Chad Zawistowski
# All rights reserved.
#
# This software is free and open source, released under the 2-clause BSD
# license as detailed in the LICENSE file.

from collections import defaultdict
from glob import glob
import os
import re
import keyword
from xml.dom import minidom
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement, parse

node_types = {}


def to_snake_case(s):
    """Convert a string to valid Python identifier in snake_case."""
    name = re.sub('_+', '_',
                  re.sub('[ .-]', '_',
                         re.sub('[><~#!?;+=\\/(){},:*\'"\[\]]', '', s))
                  ).lower().strip('_')

    if keyword.iskeyword(name) \
            or not re.match("[_A-Za-z][_a-zA-Z0-9]*$", name) \
            or name == '':
        raise ValueError(
            "'{}' is an invalid Python identifier. Original name {}".format(name, s))

    return name


def prettify_xml(elem):
    """Return a pretty-printed XML string for the Element."""
    rough_string = ElementTree.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


def parse_entity_int(s):
    """Parse integers from string according to the Entity plugin spec."""
    s = s.strip().lower()
    return int(s, 16) if s.startswith('0x') else int(s, 10)


def convert_struct(old_root, new_root):

    # name of this struct type
    try:
        struct_name = to_snake_case(old_root.attrib['class'])
        print("**** Processing type '{}'".format(struct_name))
    except KeyError:
        struct_name = to_snake_case(old_root.attrib['name'])
        # print("** Processing subtype '{}'".format(struct_name))

    new_root.set('name', struct_name)

    for old_child in old_root:

        old_offset = parse_entity_int(old_child.attrib['offset'])

        if 'string' in old_child.tag:
            # continue
            string_len = int(old_child.tag.replace('string', ''))
            if string_len == 4:
                new_child = SubElement(new_root, 'ascii')
                new_child.set('length', str(string_len))
                new_child.set('reverse', str(True))
            else:
                new_child = SubElement(new_root, 'asciiz')
                new_child.set('maxlength', str(string_len))

            new_child.set('name', to_snake_case(old_child.attrib['name']))
            new_child.set('offset', hex(old_offset))

        elif old_child.tag in ('float', 'single'):
            # continue
            new_child = SubElement(new_root, 'float32')
            new_child.set('name', to_snake_case(old_child.attrib['name']))
            new_child.set('offset', hex(old_offset))

        elif old_child.tag in ('int8', 'char', 'int16', 'short', 'int32', 'long'):
            # continue
            new_child = SubElement(new_root, {
                'int8': 'int8',
                'char': 'int8',
                'int16': 'int16',
                'short': 'int16',
                'int32': 'int32',
                'long': 'int32',
                }[old_child.tag])
            new_child.set('name', to_snake_case(old_child.attrib['name']))
            new_child.set('offset', hex(old_offset))

        elif old_child.tag in ('loneID', 'dependency'):  # odd... no loneIDs?
            # continue
            new_child = SubElement(new_root, 'reference')
            new_child.set('name', to_snake_case(old_child.attrib['name']))
            new_child.set('offset', hex(old_offset))
            if 'loneID' == old_child.tag:
                new_child.set('loneID', str(True))

        elif 'bitmask' in old_child.tag:
            # continue
            mask_size = int(old_child.tag.replace('bitmask', ''))
            if mask_size not in (8, 16, 32):
                raise ValueError('Unexpected bitmask size')

            # sort by xml attribute 'value'
            try:
                flags = sorted(((parse_entity_int(x.attrib['value']), x)
                                for x in old_child), reverse=True)
            except:
                print('Error: duplicate bitmask values in "{}"'.format(
                    old_child.attrib['name']))

                indexcount = defaultdict(int)
                for opt in old_child:
                    indexcount[opt.attrib['value']] += 1

                for opt in old_child:
                    if indexcount[opt.attrib['value']] > 1:
                        print('  {}={}'.format(opt.attrib['value'], opt.attrib['name']))

            # convert bitmask subelements to standalone flag tags
            for value, flag in flags:
                new_child = SubElement(new_root, 'flag')
                new_child.set('name', to_snake_case(flag.attrib['name']))
                new_offset = old_offset + ((mask_size - (value+1)) // 8)
                new_bit = value % 8
                new_child.set('offset', hex(new_offset))
                new_child.set('bit', str(new_bit))

        elif 'enum' in old_child.tag:
            # continue
            new_child = SubElement(new_root, old_child.tag)
            new_child.set('name', to_snake_case(old_child.attrib['name']))
            new_child.set('offset', hex(old_offset))

            # sort by xml attribute 'value'
            opts = sorted((parse_entity_int(x.attrib['value']), x)
                          for x in old_child)

            # in constrast to bitmasks, enums actually need their options as subelements
            for value, opt in opts:
                option = SubElement(new_child, 'option')
                option.set('name', to_snake_case(opt.attrib['name']))
                option.set('value', str(value))

        elif 'struct' in old_child.tag:
            new_child = SubElement(new_root, 'struct_array')
            new_child.set('name', to_snake_case(old_child.attrib['name']))
            new_child.set('offset', hex(old_offset))
            new_child.set('size', str(
                parse_entity_int(old_child.attrib['size'])))
            convert_struct(old_child, new_child)

        elif 'index' in old_child.tag:  # Todo
            new_child = SubElement(new_root, 'index')
            new_child.set('name', to_snake_case(old_child.attrib['name']))
            new_child.set('offset', hex(old_offset))

            reflexive = to_snake_case(old_child.attrib['reflexive'].replace('main:', ''))
            # print('&&&& Index: {} -> {}'.format(old_child.attrib['name'], reflexive))
            new_child.set('struct_array', reflexive)  # need to ensure is present

        elif 'color' in old_child.tag:
            try:
                new_child = SubElement(new_root, old_child.tag)
                new_child.set('name', to_snake_case(old_child.attrib['name']))
                new_child.set('offset', hex(old_offset))
            except:
                print('### {}: {}'.format(
                    old_child.tag,
                    old_child.attrib['name']))
                raise RuntimeError

        else:
            raise ValueError('Unexpected type: {}'.format(old_child.tag))

        # piece together docstring, if available
        if 'note' in old_child.attrib and 'info' in old_child.attrib:
            docstring = old_child.attrib['note'] + '; ' + old_child.attrib['info']
        elif 'note' in old_child.attrib:
            docstring = old_child.attrib['note']
        elif 'info' in old_child.attrib:
            docstring = old_child.attrib['info']
        else:
            docstring = ''

        docstring = docstring.strip('; ').replace('÷', '/')
        if docstring != '':
            new_child.set('info', docstring)

        node_types[new_child.tag] = True

    return new_root

if __name__ == '__main__':
    for filepath in glob(os.path.join(os.getcwd(), 'input', '*.xml')):
        if 'sotr' in filepath or 'vcky' in filepath:
            continue  # ignore these for now
        old_root = parse(filepath).getroot()
        new_root = Element('struct')
        res = convert_struct(old_root, new_root)
        outf = open(filepath.replace('input', 'output'), 'w')
        outf.write(prettify_xml(res))
        outf.close()
