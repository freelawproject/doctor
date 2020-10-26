import re

import boto3
import requests
from PIL import Image
from botocore import UNSIGNED
from botocore.client import Config


s3 = boto3.client("s3", config=Config(signature_version=UNSIGNED))
# We use the non-development bucket to test even though we eventually
# test save into development.  This is why we are setting these values instead
# of simply switching the defaults.
AWS_STORAGE_BUCKET_NAME = "com-courtlistener-storage"
AWS_S3_CUSTOM_DOMAIN = "https://%s.s3-%s.amazonaws.com/" % (
    AWS_STORAGE_BUCKET_NAME,
    "us-west-2",
)


def query_thumbs_db(aws_url):
    """Query the indiviual image pages of a PDF based on the thumbs.db path.

    The function queries aws and sorts files that may not have leading zeroes
    correctly by page number.
    :param aws_url: URL of image file we want to process
    :type aws_url: str
    :return: Sorted urls for document & the first response key
    :type return: tuple
    """
    kwargs = {"Bucket": AWS_STORAGE_BUCKET_NAME, "Prefix": aws_url[:-10]}
    thumbs_db_query = s3.list_objects_v2(**kwargs)
    # Filter out the proper url_paths excluding paths without Page in them
    url_paths = [
        x["Key"]
        for x in thumbs_db_query["Contents"]
        if ".db" not in x["Key"] and "Page" in x["Key"]
    ]
    lookup_key = url_paths[0]
    download_urls = [AWS_S3_CUSTOM_DOMAIN + path for path in url_paths]

    page_regex = re.compile(r"(.*Page_)(.*)(\.tif)")

    def key(item):
        m = page_regex.match(item)
        return int(m.group(2))

    download_urls.sort(key=key)
    return download_urls, lookup_key


def download_images(sorted_urls):
    """Download and save images data.

    :param sorted_urls: List of sortedd URLs for split financial disclsosure
    :return: image_list
    """
    image_list = []
    for link in sorted_urls:
        image = requests.get(link, stream=True, timeout=60 * 10).raw
        image_list.append(Image.open(image).convert("RGB"))
    return image_list
