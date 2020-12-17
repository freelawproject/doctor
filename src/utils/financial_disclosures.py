import asyncio
import io
import re
from typing import List

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


def build_and_sort_urls(urls: list) -> List[str]:
    """Build complete urls and sort them numerically

    :param urls: URL for each page sorted
    :return: List of ordered urls
    """

    url_paths = [
        x["Key"] for x in urls if ".db" not in x["Key"] and "Page" in x["Key"]
    ]
    download_urls = [AWS_S3_CUSTOM_DOMAIN + path for path in url_paths]
    page_regex = re.compile(r"(.*Page_)(.*)(\.tif)")

    def key(item):
        m = page_regex.match(item)
        return int(m.group(2))

    download_urls.sort(key=key)
    return download_urls


def find_and_sort_image_urls(aws_key: str) -> List[str]:
    """Query aws, filter and build list of image urls to download.

    All of our multiple single page splitt tiffs have a thumbnail file.
    We use the thumbs.db to find all associated files and combine them
    into a single pdf file.

    The function queries aws and sorts files that may not have leading zeroes
    correctly by page number.
    :param aws_key: URL of image file we want to process
    :type aws_key: str
    :return: Sorted urls for document & the first response key
    :type return: list
    """

    query_response = s3.list_objects_v2(
        **{"Bucket": AWS_STORAGE_BUCKET_NAME, "Prefix": aws_key[:-10]}
    )
    return build_and_sort_urls(urls=query_response["Contents"])


def download_images(sorted_urls) -> List:
    """Download images and convert to list of PIL images

    Once in an array of PIL.images we can easily convert this to a PDF.

    :param sorted_urls: List of sorted URLs for split financial disclosure
    :return: image_list
    """

    async def main(urls):
        image_list = []
        loop = asyncio.get_event_loop()
        futures = [
            loop.run_in_executor(None, requests.get, url) for url in urls
        ]
        for response in await asyncio.gather(*futures):
            image_list.append(
                Image.open(io.BytesIO(response.content)).convert("RGB"))
        return image_list

    loop = asyncio.get_event_loop()
    image_list = loop.run_until_complete(main(sorted_urls))

    return image_list
