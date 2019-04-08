#!/usr/local/bin/python

import os
import requests
import subprocess
from argparse import ArgumentParser
from shutil import rmtree
from datetime import datetime
from jinja2 import Template
from lxml import etree

CHUNK_SIZE=5242880
CMR_URL = "https://cmr.earthdata.nasa.gov/search/granules.json"
COLLECTION_IDS = [
    "C1214470533-ASF", # SENTINEL-1A_DUAL_POL_GRD_HIGH_RES
    "C1214471521-ASF", # SENTINEL-1A_DUAL_POL_GRD_MEDIUM_RES
    "C1214470682-ASF", # SENTINEL-1A_SINGLE_POL_GRD_HIGH_RES
    "C1214472994-ASF", # SENTINEL-1A_SINGLE_POL_GRD_MEDIUM_RES
    "C1327985645-ASF", # SENTINEL-1B_DUAL_POL_GRD_HIGH_RES
    "C1327985660-ASF", # SENTINEL-1B_DUAL_POL_GRD_MEDIUM_RES
    "C1327985571-ASF", # SENTINEL-1B_SINGLE_POL_GRD_HIGH_RES
    "C1327985740-ASF", # SENTINEL-1B_SINGLE_POL_GRD_MEDIUM_RES
]
USER_AGENT = "asfdaac/s1tbx-rtc"


def process_img_files(local_file,extension,create_xml):
    data_dir = local_file.replace(".dim", ".data")
    for file_name in os.listdir(data_dir):
        if file_name.endswith(".img"):
            polarization = file_name[-6:-4]
            tif_file_name = f"/output/{args.granule}_{polarization}_{extension}"
            create_geotiff_from_img(f"{data_dir}/{file_name}", tif_file_name)
            if create_xml:
                create_arcgis_xml(args.granule, f"{tif_file_name}.xml", polarization)
    cleanup(local_file)
    return None


def download_file(url):
    local_filename = url.split("/")[-1]
    headers = {'User-Agent': USER_AGENT}
    with requests.get(url, headers=headers, stream=True) as r:
        r.raise_for_status()
        with open(local_filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=CHUNK_SIZE):
                if chunk:
                    f.write(chunk)
    return local_filename


def get_download_url(granule):
    params = {
        "readable_granule_name": granule,
        "provider": "ASF",
        "collection_concept_id": COLLECTION_IDS
    }
    response = requests.get(url=CMR_URL, params=params)
    response.raise_for_status()
    cmr_data = response.json()
    download_url = ""
    if cmr_data["feed"]["entry"]:
        for product in cmr_data["feed"]["entry"][0]["links"]:
            if "data" in product["rel"]:
                return product["href"]
    return None


def get_args():
    parser = ArgumentParser(description="Radiometric Terrain Correction using the SENTINEL-1 Toolbox")
    parser.add_argument("--granule", "-g", type=str, help="Sentinel-1 Granule Name", required=True)
    parser.add_argument("--username", "-u", type=str, help="Earthdata Login Username", required=True)
    parser.add_argument("--password", "-p", type=str, help="Earthdata Login Password", required=True)
    parser.add_argument("--layover", "-l", type=bool, help="Earthdata Login Password")
    args = parser.parse_args()
    return args


def write_netrc_file(username, password):
    netrc_file = os.environ["HOME"] + "/.netrc"
    with open(netrc_file, "w") as f:
        f.write(f"machine urs.earthdata.nasa.gov login {username} password {password}")


def system_call(params):
    print(' '.join(params))
    return_code = subprocess.call(params)
    if return_code:
        exit(return_code)
    return None


def cleanup(input_file):
    os.unlink(input_file)
    if input_file.endswith(".dim"):
        data_dir = input_file.replace(".dim", ".data")
        rmtree(data_dir)


def gpt(input_file, cleanup_flag, command, *args):
    print(f"\n{command}")
    system_command = ["gpt", command, f"-Ssource={input_file}", "-t", command] + list(args)
    system_call(system_command)
    if cleanup_flag:
        cleanup(input_file)
    return f"{command}.dim"


def create_geotiff_from_img(input_file, output_file):
    print(f"\nCreating {output_file}")
    temp_file = "temp.tif"
    system_call(["gdal_translate", "-of", "GTiff", "-a_nodata", "0", input_file, temp_file])
    system_call(["gdaladdo", "-r", "average", temp_file, "2", "4", "8", "16"])
    system_call(["gdal_translate", "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE", "-co", "COPY_SRC_OVERVIEWS=YES", temp_file, output_file])
    cleanup(temp_file)


def get_xml_template():
    with open('arcgis_template.xml', 'r') as t:
        template_text = t.read()
    template = Template(template_text)
    return template


def pretty_print_xml(content):
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(content, parser)
    pretty_printed = etree.tostring(root, pretty_print=True)
    return pretty_printed


def create_arcgis_xml(input_granule, output_file, polarization):
    template = get_xml_template()
    data = {
       'now': datetime.utcnow(),
       'polarization': polarization,
       'input_granule': input_granule,
       'acquisition_year': input_granule[17:21],
    }
    rendered = template.render(data)
    pretty_printed = pretty_print_xml(rendered)
    with open(output_file, 'wb') as f:
        f.write(pretty_printed)


if __name__ == "__main__":
    args = get_args()

    print("\nFetching Granule Information")
    download_url = get_download_url(args.granule)
    if download_url is None:
        print(f"\nERROR: Either {args.granule} does exist or it is not a GRD product.")
        exit(1)

    print(f"\nDownloading granule from {download_url}")
    write_netrc_file(args.username, args.password)
    local_file = download_file(download_url)

    local_file = gpt(local_file, True, "Apply-Orbit-File")
    local_file = gpt(local_file, True, "Calibration", "-PoutputBetaBand=true", "-PoutputSigmaBand=false")
    local_file = gpt(local_file, True, "Speckle-Filter")
    local_file = gpt(local_file, True, "Multilook", "-PnRgLooks=3", "-PnAzLooks=3")
    terrain_flattening_file = gpt(local_file, True, "Terrain-Flattening", "-PreGridMethod=False")
    if args.layover:
        local_file = gpt(terrain_flattening_file, False, "SAR-Simulation", "-PdemName=SRTM 1Sec HGT", "-PsaveLayoverShadowMask=true")
        local_file = gpt(local_file, True, "Terrain-Correction", "-PimgResamplingMethod=NEAREST_NEIGHBOUR", "-PpixelSpacingInMeter=30.0", "-PsourceBands=layover_shadow_mask", "-PdemName=SRTM 1Sec HGT")
        process_img_files(local_file,'LS.tif',False)

    local_file = gpt(terrain_flattening_file, True, "Terrain-Correction", "-PpixelSpacingInMeter=30.0", "-PdemName=SRTM 1Sec HGT")


    process_img_files(local_file,"RTC.tif",True)

