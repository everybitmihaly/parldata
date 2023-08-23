import json
import time
import logging
import requests
from pathlib import Path
from collections import defaultdict

from bs4 import BeautifulSoup

SAVE_DIRECTORY = Path(__file__).resolve().parent / 'data'
METADATA_DIRECTORY = Path(__file__).resolve().parent / 'metadata'

BASE_URL = 'https://parlament.hu'

with open('PARLAMENT_APIKEY.json') as config_file:
    API_KEY = json.load(config_file)['API_KEY']


def get_xml(text):
    soup = BeautifulSoup(text, 'xml')
    return soup


def get_term_sitting_ids(soup):

    sitting_ids = set()
    for sitting in soup.find_all('ulnap'):
        sitting_id = int(sitting.get_text(strip=True))
        sitting_ids.add(sitting_id)

    return sorted(sitting_ids)


def get_sitting_speech_ids(sitting_speech_list_soup):

    sitting_speech_id_strs = [tag.get_text(strip=True) for tag in sitting_speech_list_soup.find_all('sorszam')]
    sitting_speech_ids = set()
    for speech_id in sitting_speech_id_strs:
        if speech_id != 'nincs':
            sitting_speech_ids.add(int(speech_id))

    return sorted(sitting_speech_ids)


def fetch_speech_content(p_ckl, p_uln, p_felsz, access_token):

    url = f'{BASE_URL}/cgi-bin/web-api-pub/felszolalas.cgi?access_token={access_token}&p_ckl={p_ckl}&p_uln={p_uln}' \
          f'&p_felsz={p_felsz}'
    try:
        response = requests.get(url)
    except (requests.exceptions.ConnectionError, requests.exceptions.RequestException)  as e:
        logging.debug(f'Requesting {p_ckl}-{p_uln}-{p_felsz} failed with {e} ! Retrying in 5 seconds...')
        time.sleep(5)
        response = fetch_speech_content(p_ckl, p_uln, p_felsz, access_token)

    response.encoding = 'utf-8'

    response_text = response.text

    if response_text == '<?xml version="1.0" encoding="utf-8"?>\n<felszolalas/>\n':
        return None

    return response_text


def fetch_sitting_speech_listing(p_ckl, p_nap, access_token):

    url = f'{BASE_URL}/cgi-bin/web-api-pub/felszolalasok.cgi?access_token={access_token}&p_ckl={p_ckl}&p_nap={p_nap}'
    response = requests.get(url)
    response.encoding = 'utf-8'

    response_text = response.text

    if response_text == '<?xml version="1.0" encoding="utf-8"?>\n<felszolalasok/>\n':
        return None

    return response_text


def fetch_term_sitting_listing(p_ckl, access_token):
    """
    Fetch xml of term sittings - the first layer of xmls.
    :param p_ckl: term_number
    :param access_token: API ACCESS TOKEN
    :return:
    """

    print('WHY ARE WE DOING THIS?')
    p_ckl = str(p_ckl)

    url = f'{BASE_URL}/cgi-bin/web-api-pub/ulesnap.cgi?access_token={access_token}&p_ckl={p_ckl}'
    response = requests.get(url)
    response.encoding = 'utf-8'

    response_text = response.text

    if response_text == '<?xml version="1.0" encoding="utf-8"?>\n<ulesnapok/>\n':
        return None

    return response_text


def sort_and_convert_to_dict(defaultdict_variable):

    normal_sorted_dict = {key: defaultdict_variable[key] for key in sorted(defaultdict_variable.keys())}

    values_sample = list(normal_sorted_dict.values())[0]

    if isinstance(values_sample, (dict, defaultdict)):
        return {key: sort_and_convert_to_dict(value) for key, value in normal_sorted_dict.items()}
    elif isinstance(values_sample, list):
        return {key: sorted(value) for key, value in normal_sorted_dict.items()}


def build_collections_dict(save_directory):
    """
    :param save_directory: Directory where API response xmls are saved
        structure should be:
            - term_dir
                - sitting_dir
                    - speech_dir
            - term_dir
            ...
    :return: collections dictionary that contains all saved speeches
    """

    collections_dict = defaultdict(lambda: defaultdict(list))

    for term_dir_path in save_directory.iterdir():
        if term_dir_path.is_dir() and term_dir_path.stem.isnumeric():  # take only directories
            # take only directories that are titled after their term (e.g.: 42)
            term_num = int(term_dir_path.stem)

            for sitting_dir_path in term_dir_path.iterdir():
                if sitting_dir_path.is_dir() and sitting_dir_path.stem.isnumeric():  # take only directories
                    sitting_num = int(sitting_dir_path.stem)

                    for speech_file_path in sitting_dir_path.glob('*.xml'):
                        speech_num = speech_file_path.stem.split('-')[-1]
                        if speech_num.isnumeric():
                            collections_dict[term_num][sitting_num].append(int(speech_num))

    return sort_and_convert_to_dict(collections_dict)


def build_metadata_dict(metadata_dir, api_key):

    metadata_list = []

    for term_id in range(36, 60):  # Current term is 42

        # check if term xml exists
        term_xml_path = metadata_dir / f'term_{term_id}.xml'
        if term_xml_path.is_file() is False:
            # download term xml
            term_xml_response_text = fetch_term_sitting_listing(term_id, api_key)

            if term_xml_response_text is not None:

                term_xml = get_xml(term_xml_response_text)

                with open(term_xml_path, 'w') as fh:
                    fh.write(term_xml.prettify())
            else:
                break

        else:
            with open(term_xml_path) as fh:
                term_xml = get_xml(fh.read())

        term_sitting_ids = get_term_sitting_ids(term_xml)

        for sitting_id in term_sitting_ids:
            # check if sittings direcotry exists
            term_directory_path = metadata_dir / str(term_id)
            if term_directory_path.is_dir() is False:
                term_directory_path.mkdir(exist_ok=True, parents=True)

            sittings_xml_path = term_directory_path / f'sittings_{sitting_id}.xml'

            if sittings_xml_path.is_file() is False:

                sittings_xml_response_text = fetch_sitting_speech_listing(term_id, sitting_id, api_key)

                # If none it means the response had no content - not a valid term-sitting combination
                if sittings_xml_response_text is not None:
                    sittings_xml = get_xml(sittings_xml_response_text)

                    with open(sittings_xml_path, 'w') as fh:
                        fh.write(sittings_xml.prettify())
                        logging.info(f'SAVED XML {sittings_xml.stem}')

            else:
                with open(sittings_xml_path) as fh:
                    sittings_xml = get_xml(fh.read())

            sitting_speech_ids = get_sitting_speech_ids(sittings_xml)

            for speech_id in sitting_speech_ids:
                metadata_list.append((term_id, sitting_id, speech_id))

    return metadata_list


def generate_download_dict(metadata, collections_dict, start=(-1, -1, -1)):
    """
    :param metadata:
    :param collections_dict:
    :param start:
        - None: will download all missing
        - Tuple: (term_id, sitting_id, speech_id) will add only everything following given id tuple
    :return:
    """

    to_download = defaultdict(lambda: defaultdict(list))
    start_from = Start(*start)

    for term_id, sitting_id, speech_id in metadata:
        if start_from.later(term_id, sitting_id, speech_id):  # returns True if speech is later than speech start_from.

            if speech_id not in collections_dict.get(term_id, {}).get(sitting_id, ()):
                print(term_id, sitting_id, speech_id)
                to_download[term_id][sitting_id].append(speech_id)

    return sort_and_convert_to_dict(to_download)


class Start:

    def __init__(self, term_id, sitting_id, speech_id):
        self.term_id = term_id
        self.sitting_id = sitting_id
        self.speech_id = speech_id

    def later(self, compare_term, compare_sitting, compare_speech):
        if self.term_id <= compare_term:
            if self.sitting_id == compare_sitting and self.speech_id <= compare_speech:
                return True
            elif self.sitting_id < compare_sitting:
                return True

        return False


def download_speeches(to_download, save_directory, api_key):
    for term_id, term_data in to_download.items():
        for sitting_id, speech_ids in term_data.items():

            sitting_directory = save_directory / str(term_id) / str(sitting_id)
            if sitting_directory.is_dir() is False:
                sitting_directory.mkdir(exist_ok=True, parents=True)

            for speech_id in speech_ids:
                speech_xml_text = fetch_speech_content(term_id, sitting_id, speech_id, api_key)

                speech_xml = get_xml(speech_xml_text)

                with open(sitting_directory / f'{term_id}-{sitting_id}-{speech_id}.xml', 'w') as fh:
                    fh.write(speech_xml.prettify())


if __name__ == '__main__':

    # 1. Check save directory and metadata directory, build collections, metadata, and download data.
    if SAVE_DIRECTORY.is_dir() is False:
        SAVE_DIRECTORY.mkdir(parents=True, exist_ok=True)

    if METADATA_DIRECTORY.is_dir() is False:
        METADATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    collections_dictionary = build_collections_dict(SAVE_DIRECTORY)
    metadata_list = build_metadata_dict(METADATA_DIRECTORY, API_KEY)

    download_dict = generate_download_dict(metadata_list, collections_dictionary)

    download_speeches(download_dict, SAVE_DIRECTORY, API_KEY)
