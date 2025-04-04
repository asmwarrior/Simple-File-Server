#!/usr/bin/env python

"""Simple HTTP Server With Upload and Authentication.

This module builds on BaseHTTPServer by implementing the standard GET
and HEAD requests in a fairly straightforward manner.

"""

__author__ = "bones7456"
__contributors__ = "wonjohnchoi, shellster, RDCH106, vgonisanz"

default_setting_file_name = 'config/default.json'
setting_file_name = 'config/config.json'
settings = ""

import os
import sys
import posixpath
# python 2 only
# import BaseHTTPServer
# python 3
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib
import cgi
import html
import shutil
import mimetypes
import re

# python 2
# try:
#     from cStringIO import StringIO
# except ImportError:
#     from StringIO import StringIO

# python 3
from io import StringIO    
    
import base64
import json


class BytesIOWrapper:
    def __init__(self, string_buffer, encoding='utf-8'):
        self.string_buffer = string_buffer
        self.encoding = encoding

    def __getattr__(self, attr):
        return getattr(self.string_buffer, attr)

    def read(self, size=-1):
        if isinstance(self.string_buffer, StringIO):
            content = self.string_buffer.read(size)
            return content.encode(self.encoding)            
        else:
            return self.string_buffer.read(size)

    def write(self, b):
        content = b.decode(self.encoding)
        return self.string_buffer.write(content)

# python3
# encode("utf-8")
def key():
    data_string = '%s:%s' % (settings["username"], settings["password"])
    # https://stackoverflow.com/questions/36714281/python-base64-encode-to-string
    return base64.b64encode(data_string.encode("utf-8")).decode('ascii')

def read_config():
    global settings
    global extensions_map
    exist = os.path.isfile(setting_file_name)
    if not exist:
        print('Creating config file...')
        shutil.copyfile(default_setting_file_name, setting_file_name)
        print('Edit config.json and launch the script again.')
        sys.exit()

    with open(setting_file_name) as data_file:
        settings = json.load(data_file)

        ####################################################################
        #Load default mimetypes and update them with config.json extensions#
        ####################################################################
        if not mimetypes.inited:
            mimetypes.init()  # try to read system mime.types
        extensions_map = mimetypes.types_map.copy()
        extensions_map.update({
            '': 'application/octet-stream'  # Default
        })
        extensions_map.update(settings['extensions'])  # Read extensions from config.json
        #####################################################################
    return

class Counter:
    ''' instantiate only once '''
    def __init__(self):
        import sqlite3
        print('making sqlite3 database')
        self.conn = sqlite3.connect('simple-file-server.db')
        self.cursor = self.conn.cursor()
        self.cursor.execute('''CREATE TABLE IF NOT EXISTS counter
                  (fullpath text primary key, count integer)''')

    def incr_counter(self, path):
        """ Increase the counter that counts how many times a path is visited """
        res = self.read_counter(path)
        # print 'incr_counter:', path, res, '->', res + 1
        res += 1
        self.cursor.execute('REPLACE INTO counter(fullpath, count) VALUES(?, ?)', (path, res))
        self.conn.commit()

    def read_counter(self, path):
        """ Read the counter that counts how many times a path is visited """
        self.cursor.execute('SELECT * FROM "counter" WHERE "fullpath"=?', (path,))
        row = self.cursor.fetchone()
        count = 0
        if row != None : count = row[1]
        # print 'read_counter:', path, count
        return count


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    """Simple HTTP request handler with GET/HEAD/POST commands.

    This serves files from the current directory and any of its
    subdirectories.  The MIME type for files is determined by
    calling the .guess_type() method. And can reveive file uploaded
    by client.

    The GET/HEAD/POST requests are identical except that the HEAD
    request omits the actual contents of the file.

    """
    counter = Counter()

    def do_HEAD(self):
        """Serve a HEAD request."""
        f = self.send_head()
        if f:
            f.close()

    def is_authenticated(self):
        # Python3's HTTPMessage object has no attribute getheaders, so fix like below
        auth_header = self.headers.get('Authorization')
        return auth_header and auth_header == 'Basic ' + key()

    def do_AUTHHEAD(self):
        self.send_response(401)
        self.send_header('WWW-Authenticate', 'Basic realm=\"%s\"' % settings["realm"])
        self.send_header('Content-Type', 'text/html')
        self.end_headers()

    def try_authenticate(self):
        if not self.is_authenticated():
            self.do_AUTHHEAD()
            print('Not authenticated')
            self.wfile.write('Not authenticated')
            return False
        return True

    def do_GET(self):
        if not self.path == "/logout":
            if not self.try_authenticate():
                return
            else:
                print('Authenticated')

        if self.path == "/logout":
            print('Logout')
            self.send_response(401)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'Logout')

        else:
            f = self.send_head()
            if f:
                #self.copyfile(f, self.wfile) 
                self.wfile.write(BytesIOWrapper(f).read()) #python 3
                f.close()

    def do_POST(self):
        """Serve a POST request."""

        if not self.try_authenticate():
            return
        print('authenticated')


        r, info = self.deal_post_data()
        print(r, info, "by: ", self.client_address)
        f = StringIO()
        self.writeHeader(f, "Upload Result")
        f.write("<h2>Upload Result Page</h2>\n")
        f.write("<hr>\n")
        if r:
            f.write("<strong>Success:</strong>")
        else:
            f.write("<strong>Failed:</strong>")
        f.write(info)
        f.write("\n<br><br>\n<a href=\"%s\">back</a>\n" % self.headers['referer'])
        self.writeFooter(f)
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def deal_post_data(self):
        boundary = self.headers.plisttext.split("=")[1]
        remainbytes = int(self.headers['content-length'])
        line = self.rfile.readline()
        remainbytes -= len(line)
        if not boundary in line:
            return (False, "Content NOT begin with boundary")
        line = self.rfile.readline()
        remainbytes -= len(line)
        fn = re.findall(r'Content-Disposition.*name="file"; filename="(.*)"', line)
        if not fn:
            return (False, "Can't find out file name...")
        path = self.url_path_to_file_path(self.path)
        fn = os.path.join(path, fn[0])
        if os.path.exists(fn):
            return (False, "The path already exists, you cannot overwrite it.")
        line = self.rfile.readline()
        remainbytes -= len(line)
        line = self.rfile.readline()
        remainbytes -= len(line)
        try:
            out = open(fn, 'wb')
        except IOError:
            return (False, "Can't create file to write, do you have permission to write?")

        preline = self.rfile.readline()
        remainbytes -= len(preline)
        while remainbytes > 0:
            line = self.rfile.readline()
            remainbytes -= len(line)
            if boundary in line:
                preline = preline[0:-1]
                if preline.endswith('\r'):
                    preline = preline[0:-1]
                out.write(preline)
                out.close()
                return (True, "File '%s' upload success!" % fn)
            else:
                out.write(preline)
                preline = line
        return (False, "Unexpect Ends of data.")

    def send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.

        """
        print('url_path', self.path)
        file_path = self.url_path_to_file_path(self.path)
        print('file_path', file_path)
        f = None
        if os.path.isdir(file_path):
            if not self.path.endswith('/'):
                # redirect browser - doing basically what apache does
                self.send_response(301)
                self.send_header("Location", self.path + "/")
                self.end_headers()
                return None
            for index in "index.html", "index.htm":
                index = os.path.join(file_path, index)
                if os.path.exists(index):
                    file_path = index
                    break

        self.counter.incr_counter(file_path)

        if os.path.isdir(file_path):
            return self.list_directory(file_path)
        ctype = self.guess_type(file_path)

        try:
            # Always read in binary mode. Opening files in text mode may cause
            # newline translations, making the actual size of the content
            # transmitted *less* than the content-length!
            f = open(file_path, 'rb')
        except IOError:
            self.send_error(404, "File not found " + file_path)
            return None
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if (settings['force-download'] == True):
            self.send_header("Content-Disposition", "attachment")
        fs = os.fstat(f.fileno())
        self.send_header("Content-Length", str(fs[6]))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        self.end_headers()
        return f

    def list_directory(self, dir_path):
        """Helper to produce a directory listing (absent index.html).

        Return value is either a file object, or None (indicating an
        error).  In either case, the headers are sent, making the
        interface the same as for send_head().

        """
        try:
            list = os.listdir(dir_path)
        except os.error:
            self.send_error(404, "No permission to list directory")
            return None
        list.sort(key=lambda a: a.lower())
        if dir_path != '/':
            list = ['..'] + list
        f = StringIO()
        # python 3
        # https://stackoverflow.com/questions/62470666/getting-this-error-with-py2-7-as-well-as-with-py3-7
        displaypath = html.escape(urllib.parse.unquote(self.path))

        self.writeHeader(f, "Simple-File-Server")
        f.write("<h2>Directory listing for <small>%s (frequently used directories are more reddish)</small></h2>\n" % displaypath)
        f.write("<hr>\n")
        f.write("<form ENCTYPE=\"multipart/form-data\" method=\"post\" class=\"form-inline\">")
        f.write("<div class=\"form-group\"><input name=\"file\" type=\"file\"/ class=\"btn btn-default\"></div>")
        f.write("&nbsp;&nbsp;&nbsp;<div class=\"form-group\"><input type=\"submit\" value=\"upload\"/ class=\"btn btn-primary\"></div></form>\n")
        f.write("<hr>\n<ul>\n")

        tot_counts = 0
        for name in list:
            child_file_path = posixpath.normpath(os.path.join(dir_path, name))
            counts = self.counter.read_counter(child_file_path)
            print(child_file_path, counts)
            tot_counts += counts

        # avoid divide by zero error
        if tot_counts == 0:
            tot_counts += 1

        for name in list:
            child_file_path = posixpath.normpath(os.path.join(dir_path, name))
            displayname = linkname = name
            # Append / for directories or @ for symbolic links
            if os.path.isdir(child_file_path):
                displayname = name + "/"
                linkname = name + "/"
            if os.path.islink(child_file_path):
                displayname = name + "@"
                # Note: a link to a directory displays with @ and links with /
            counts = self.counter.read_counter(child_file_path)
            # red portion of rgb value. with **0.2, it's overall more reddish
            rgb_r = 255 * (float(counts) / tot_counts) ** 0.2
            f.write('<li><a style="color:rgb(%d,0,0)" href="%s">%s</a>\n'
                    % (rgb_r, urllib.parse.quote(linkname), html.escape(displayname)))
        f.write("</ul>\n")
        self.writeFooter(f)
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        return f

    @staticmethod
    def writeHeader(f, title):
        f.write('<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 3.2 Final//EN">\n')
        f.write("<html>\n<head>\n<link rel=\"icon\" href=\"https://raw.githubusercontent.com/RDCH106/Simple-File-Server/master/SFS.ico\">")
        f.write("<link rel=\"stylesheet\" href=\"https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css\">\n")
        f.write("<title>%s</title>\n</head>\n" % title)
        f.write("<body>\n<div class=\"container\">\n")

    @staticmethod
    def writeFooter(f):
        f.write("<hr>\n<small>\nPowered By: <a href=\"https://github.com/RDCH106\">RDCH106</a>, check new version at ")
        f.write("<a href=\"https://github.com/RDCH106/Simple-File-Server\">GitHub</a>\n</small>\n")
        f.write("<h4><a href=\"/logout\">Logout</a></h4>\n")
        f.write("</div>\n</body>\n</html>\n")

    @staticmethod
    def url_path_to_file_path(url_path):
        # abandon query parameters
        url_path = url_path.split('?',1)[0]
        url_path = url_path.split('#',1)[0]
        # python 3
        url_path = posixpath.normpath(urllib.parse.unquote(url_path))
        return settings["base_url"] + url_path

    @staticmethod
    def copyfile(source, outputfile):
        """Copy all data between two file objects.

        The SOURCE argument is a file object open for reading
        (or anything with a read() method) and the DESTINATION
        argument is a file object open for writing (or
        anything with a write() method).

        The only reason for overriding this would be to change
        the block size or perhaps to replace newlines by CRLF
        -- note however that this the default server uses this
        to copy binary data as well.

        """
        shutil.copyfileobj(source, outputfile)

    def guess_type(self, path):
        """Guess the type of a file.

        Argument is a PATH (a filename).

        Return value is a string of the form type/subtype,
        usable for a MIME Content-Type header.

        The default implementation looks the file's extension
        up in the table self.extensions_map, using application/octet-stream
        as a default; however it would be permissible (if
        slow) to look inside the data to make a better guess.

        """

        base, ext = posixpath.splitext(path)
        if ext in extensions_map:
            return extensions_map[ext]
        ext = ext.lower()
        if ext in extensions_map:
            return extensions_map[ext]
        else:
            return extensions_map['']

if __name__ == '__main__':
    print('Reading settings from %s...' %(setting_file_name))
    read_config()
    print('listening on %s:%d with key %s' %(settings["host"], int(settings["port"]), key()))
    server = HTTPServer((settings["host"], int(settings["port"])), SimpleHTTPRequestHandler)
    print('Starting server, use <Ctrl-C> to stop')
    server.serve_forever()
