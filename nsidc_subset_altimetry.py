#!/usr/bin/env python
u"""
nsidc_subset_altimetry.py
Written by Tyler Sutterley (01/2019)

Program to acquire subset altimetry datafiles from the NSIDC API:
https://wiki.earthdata.nasa.gov/display/EL/How+To+Access+Data+With+Python
https://nsidc.org/support/faq/what-options-are-available-bulk-downloading-data-
	https-earthdata-login-enabled
https://nsidc.org/support/how/2018-agu-tutorial
https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html
http://www.voidspace.org.uk/python/articles/authentication.shtml#base64

Register with NASA Earthdata Login system:
https://urs.earthdata.nasa.gov

Add NSIDC_DATAPOOL_OPS to NASA Earthdata Applications
https://urs.earthdata.nasa.gov/oauth/authorize?client_id=_JLuwMHxb2xX6NwYTb4dRA

CALLING SEQUENCE:
	python nsidc_subset_altimetry.py -T 2018-11-23T00:00:00,2018-11-23T23:59:59
		-B -50.33333,68.56667,-49.33333,69.56667 --version=001 -F NetCDF4-CF
		--user=<username> -V ATL03
	where <username> is your NASA Earthdata username

INPUTS:
	GLAH12: GLAS/ICESat L2 Antarctic and Greenland Ice Sheet Altimetry Data
	ILATM2: Airborne Topographic Mapper Icessn Elevation, Slope, and Roughness
	ILATM1B: Airborne Topographic Mapper QFIT Elevation
	ILVIS1B: Land, Vegetation and Ice Sensor Geolocated Return Energy Waveforms
	ILVIS2: Geolocated Land, Vegetation and Ice Sensor Surface Elevation Product
	ATL03: Global Geolocated Photon Data
	ATL04: Normalized Relative Backscatter
	ATL06: Land Ice Height
	ATL07: Sea Ice Height
	ATL08: Land and Vegetation Height
	ATL09: Atmospheric Layer Characteristics
	ATL10: Sea Ice Freeboard
	ATL12: Ocean Surface Height
	ATL13: Inland Water Surface Height

COMMAND LINE OPTIONS:
	--help: list the command line options
	-D X, --directory=X: working data directory
	-U X, --user=X: username for NASA Earthdata Login
	--version: version of the dataset to use
	-B X, --bbox=X: Bounding box (lonmin,latmin,lonmax,latmax)
	-T X, --time=X: Time range (comma-separated start and end)
	-F X, --format=X: Output data format (TABULAR_ASCII, NetCDF4)
	-M X, --mode=X: Local permissions mode of the files processed
	-V, --verbose: Verbose output of processing
	-Z, --unzip: Unzip dataset from NSIDC subsetting service

UPDATE HISTORY:
	Written 01/2019
"""
from __future__ import print_function

import sys
import os
import io
import re
import time
import getopt
import shutil
import base64
import getpass
import zipfile
import builtins
import posixpath
import dateutil.parser
if sys.version_info[0] == 2:
	from cookielib import CookieJar
	import urllib2
else:
	from http.cookiejar import CookieJar
	import urllib.request as urllib2

#-- PURPOSE: check internet connection
def check_connection():
	#-- attempt to connect to https host for NSIDC
	try:
		urllib2.urlopen('https://n5eil01u.ecs.nsidc.org/',timeout=1)
	except urllib2.URLError:
		raise RuntimeError('Check internet connection')
	else:
		return True

#-- PURPOSE: program to acquire subsetted NSIDC data
def nsidc_subset_altimetry(filepath, PRODUCT, VERSION, BBOX, TIME, FORMAT,
	USER='', PASSWORD='', MODE=None, CLOBBER=False, VERBOSE=False, UNZIP=False):

	#-- https://docs.python.org/3/howto/urllib2.html#id5
	#-- create a password manager
	password_mgr = urllib2.HTTPPasswordMgrWithDefaultRealm()
	#-- Add the username and password for NASA Earthdata Login system
	password_mgr.add_password(None, 'https://urs.earthdata.nasa.gov',
		USER, PASSWORD)
	#-- Encode username/password for request authorization headers
	base64_string = base64.b64encode('{0}:{1}'.format(USER,PASSWORD).encode())
	#-- Create cookie jar for storing cookies. This is used to store and return
	#-- the session cookie given to use by the data server (otherwise will just
	#-- keep sending us back to Earthdata Login to authenticate).
	cookie_jar = CookieJar()
	#-- create "opener" (OpenerDirector instance)
	opener = urllib2.build_opener(
		urllib2.HTTPBasicAuthHandler(password_mgr),
	    #urllib2.HTTPHandler(debuglevel=1),  # Uncomment these two lines to see
	    #urllib2.HTTPSHandler(debuglevel=1), # details of the requests/responses
		urllib2.HTTPCookieProcessor(cookie_jar))
	#-- add Authorization header to opener
	authorization_header = "Basic {0}".format(base64_string.decode())
	opener.addheaders = [("Authorization", authorization_header)]
	#-- Now all calls to urllib2.urlopen use our opener.
	urllib2.install_opener(opener)
	#-- All calls to urllib2.urlopen will now use handler
	#-- Make sure not to include the protocol in with the URL, or
	#-- HTTPPasswordMgrWithDefaultRealm will be confused.

	#-- product and version flags
	product_flag = '?short_name={0}'.format(PRODUCT)
	version_flag = '&version={0}'.format(VERSION) if VERSION else ''
	#-- if using time start and end to temporally subset data
	if TIME:
		#-- verify that start and end times are in ISO format
		start_time = dateutil.parser.parse(TIME[0]).isoformat()
		end_time = dateutil.parser.parse(TIME[1]).isoformat()
		time_flag = '&time={0},{1}'.format(start_time, end_time)
	else:
		time_flag = ''
	#-- if using a bounding box to spatially subset data
	#-- min_lon,min_lat,max_lon,max_lat
	if BBOX:
		bounds_flag = '&bounding_box={0:f},{1:f},{2:f},{3:f}'.format(*BBOX)
		bbox_flag = '&bbox={0:f},{1:f},{2:f},{3:f}'.format(*BBOX)
	else:
		bounds_flag = ''
		bbox_flag = ''
	#-- if changing the output format
	format_flag = '&format={0}'.format(FORMAT) if FORMAT else ''

	#-- remote https server for NSIDC Data
	HOST = posixpath.join('https://n5eil02u.ecs.nsidc.org','egi','request')
	remote_file = '{0}{1}{2}{3}{4}{5}{6}'.format(HOST,product_flag,version_flag,
		bounds_flag,bbox_flag,time_flag,format_flag)

	#-- local file
	today = time.strftime('%Y-%m-%dT%H-%M-%S',time.localtime())
	#-- download as either zipped file (default) or unzip to a directory
	if UNZIP:
		#-- Create and submit request. There are a wide range of exceptions
		#-- that can be thrown here, including HTTPError and URLError.
		request = urllib2.Request(remote_file)
		response = urllib2.urlopen(request)
		#-- read to BytesIO object
		fid = io.BytesIO(response.read())
		#-- use zipfile to extract contents from bytes
		remote_data = zipfile.ZipFile(fid)
		subdir = '{0}_{1}'.format(PRODUCT,today)
		print('{0} -->\n'.format(remote_file)) if VERBOSE else None
		#-- extract each member and convert permissions to MODE
		for member in remote_data.filelist:
			local_file = os.path.join(filepath,subdir,member.filename)
			print('\t{0}\n'.format(local_file)) if VERBOSE else None
			remote_data.extract(member, path=os.path.join(filepath,subdir))
			os.chmod(local_file, MODE)
		#-- close the zipfile object
		remote_data.close()
	else:
		#-- Printing files transferred if VERBOSE
		local_file = os.path.join(filepath,'{0}_{1}.zip'.format(PRODUCT,today))
		args = (remote_file,local_file)
		print('{0} -->\n\t{1}\n'.format(*args)) if VERBOSE else None
		#-- Create and submit request. There are a wide range of exceptions
		#-- that can be thrown here, including HTTPError and URLError.
		request = urllib2.Request(remote_file)
		response = urllib2.urlopen(request)
		#-- copy contents to local file using chunked transfer encoding
		#-- transfer should work properly with ascii and binary data formats
		CHUNK = 16 * 1024
		with open(local_file, 'wb') as f:
			shutil.copyfileobj(response, f, CHUNK)
		#-- keep remote modification time of file and local access time
		# os.utime(local_file, (os.stat(local_file).st_atime, remote_mtime))
		#-- convert permissions to MODE
		os.chmod(local_file, MODE)

#-- PURPOSE: help module to describe the optional input parameters
def usage():
	print('\nHelp: {0}'.format(os.path.basename(sys.argv[0])))
	print(' -U X, --user=X\t\tUsername for NASA Earthdata Login')
	print(' -D X, --directory=X\tWorking data directory')
	print(' --version\t\tVersion of the dataset to use')
	print(' -B X, --bbox=X\t\tBounding box (lonmin,latmin,lonmax,latmax)')
	print(' -T X, --time=X\t\tTime range (comma-separated start and end)')
	print(' -F X, --format=X\tOutput data format (TABULAR_ASCII, NetCDF4)')
	print(' -M X, --mode=X\t\tPermission mode of files processed')
	print(' -V, --verbose\t\tVerbose output of processing')
	print(' -Z, --unzip\t\tUnzip dataset from NSIDC subsetting service\n')

#-- Main program that calls nsidc_subset_altimetry()
def main():
	#-- Read the system arguments listed after the program
	long_options = ['help','version=','bbox=','time=','format=','user=',
		'directory=','mode=','verbose','unzip']
	optlist,arglist = getopt.getopt(sys.argv[1:],'hU:D:B:T:F:M:VZ',long_options)

	#-- command line parameters
	VERSION = None
	BBOX = None
	TIME = None
	FORMAT = None
	USER = ''
	#-- working data directory
	DIRECTORY = os.getcwd()
	#-- permissions mode of the local directories and files (number in octal)
	MODE = 0o775
	VERBOSE = False
	UNZIP = False
	for opt, arg in optlist:
		if opt in ("-h","--help"):
			usage()
			sys.exit()
		elif opt in ("-U","--user"):
			USER = arg
		elif opt in ("-D","--directory"):
			DIRECTORY = os.path.expanduser(arg)
		elif opt in ("--version"):
			VERSION = arg
		elif opt in ("-B","--bbox"):
			BBOX = [float(i) for i in arg.split(',')]
		elif opt in ("-T","--time"):
			TIME = arg.split(',')
		elif opt in ("-F","--format"):
			FORMAT = arg
		elif opt in ("-M","--mode"):
			MODE = int(arg, 8)
		elif opt in ("-V","--verbose"):
			VERBOSE = True
		elif opt in ("-Z","--unzip"):
			UNZIP = True

	#-- Products for the NSIDC subsetter
	P = {}
	#-- ICESat/GLAS
	P['GLAH12'] = 'GLAS/ICESat L2 Antarctic and Greenland Ice Sheet Altimetry'
	#-- Operation IceBridge
	P['ILATM2'] = 'Icebridge Airborne Topographic Mapper Icessn Product'
	P['ILATM1B'] = 'Icebridge Airborne Topographic Mapper QFIT Elevation'
	P['ILVIS1B'] = 'Icebridge LVIS Geolocated Return Energy Waveforms'
	P['ILVIS2'] = 'Icebridge Land, Vegetation and Ice Sensor Elevation Product'
	#-- ICESat-2/ATLAS
	P['ATL03'] = 'Global Geolocated Photon Data'
	P['ATL04'] = 'Normalized Relative Backscatter'
	P['ATL06'] = 'Land Ice Height'
	P['ATL07'] = 'Sea Ice Height'
	P['ATL08'] = 'Land and Vegetation Height'
	P['ATL09'] = 'Atmospheric Layer Characteristics'
	P['ATL10'] = 'Sea Ice Freeboard'
	P['ATL12'] = 'Ocean Surface Height'
	P['ATL13'] = 'Inland Water Surface Height'

	#-- enter dataset to transfer as system argument
	if not arglist:
		for key,val in P.items():
			print('{0}: {1}'.format(key, val))
		raise Exception('No System Arguments Listed')

	#-- NASA Earthdata hostname
	HOST = 'urs.earthdata.nasa.gov'
	#-- check that NASA Earthdata credentials were entered
	if not USER:
		USER = builtins.input('Username for {0}: '.format(HOST))
	#-- enter password securely from command-line
	PASSWORD = getpass.getpass('Password for {0}@{1}: '.format(USER,HOST))

	#-- check internet connection before attempting to run program
	if check_connection():
		#-- check that each data product entered was correctly typed
		keys = ','.join(sorted([key for key in P.keys()]))
		for p in arglist:
			if p not in P.keys():
				raise IOError('Incorrect Data Product Entered ({0})'.format(p))
			nsidc_subset_altimetry(DIRECTORY, p, VERSION, BBOX, TIME, FORMAT,
				USER=USER, PASSWORD=PASSWORD, MODE=MODE, VERBOSE=VERBOSE,
				UNZIP=UNZIP)

#-- run main program
if __name__ == '__main__':
	main()
