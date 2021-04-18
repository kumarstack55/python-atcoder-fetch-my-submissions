#!/usr/bin/env python
from logging import getLogger
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver
from time import sleep
from typing import Any
import argparse
import chromedriver_binary  # noqa: F401
import copy
import html
import json
import logging
import re
import requests
import toml


DIR_SUBMISSION = 'atcoder-submissions'
WAIT_SEC = 3


logger = getLogger(__name__)


class Submission(object):
    ''' 提出を表現するクラスです。 '''

    def __init__(self, sub_dic):
        self._sub_dic = sub_dic
        self._id = sub_dic["id"]
        self._contest_id = sub_dic["contest_id"]
        self._problem_id = sub_dic["problem_id"]
        self._epoch_second = sub_dic["epoch_second"]
        self._language = sub_dic["language"]
        self._result = sub_dic["result"]

    def _split_problem_id(self) -> str:
        # problem_id が codefestival_2016_qualB_a のように、
        # 複数のアンダースコアを含むことがある。
        # そのため、最後のアンダースコアを境に得るようにする。
        return re.search(r'^(.+?)_(.)$', self.problem_id)

    def get_problem_id_postfix(self) -> str:
        m = self._split_problem_id()
        assert m
        postfix = m.group(2)

        # 古い問題の場合は数字なので、アルファベットに戻す。
        if postfix.isdigit():
            postfix = chr(int(postfix)+ord('a')-1)

        return postfix

    def get_contest_id_from_problem_id(self) -> str:
        m = self._split_problem_id()
        assert m
        return m.group(1)

    def is_ac(self) -> bool:
        return self.result == "AC"

    def get_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self._sub_dic)

    @property
    def id(self) -> int:
        return self._id

    @property
    def contest_id(self) -> str:
        return self._contest_id

    @property
    def problem_id(self) -> str:
        return self._problem_id

    @property
    def epoch_second(self) -> int:
        return self._epoch_second

    @property
    def language(self) -> str:
        return self._language

    @property
    def result(self) -> str:
        return self._result

    def __repr__(self) -> str:
        return "<Submission %s>" % (str(self._sub_dic))


class JSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Submission):
            return obj.get_dict()
        return JSONEncoder.default(self, obj)


def _json_dump(obj, fp) -> str:
    json.dump(obj, fp, cls=JSONEncoder, indent=2, sort_keys=True)


def _get_results_from_atcoder_problems(
        user_id: str) -> list[dict[str, Any]]:
    ''' 提出データを得る。 '''
    logger.debug("_get_results_from_atcoder_problems()")
    logger.debug(f"{user_id=}")
    api_path = "https://kenkoooo.com/atcoder/atcoder-api/results?user="
    api_url = api_path + user_id
    resp = requests.get(api_url)
    results = resp.json()
    return results


def _get_latest_ac_subs_from_atcoder_problems(
        user_id: str) -> list[Submission]:
    logger.debug("_get_latest_ac_subs_from_atcoder_problems()")
    ''' 指定ユーザの取得対象の提出を得る '''
    # すべての提出を得る。
    results = _get_results_from_atcoder_problems(user_id)
    subs = list(map(lambda sub_dic: Submission(sub_dic), results))

    # 提出をJSONファイルに保存する。
    with open(str(Path(DIR_SUBMISSION) / "results.json"), "w") as f:
        _json_dump(subs, f)

    # AC に限定する。
    ac_subs = list(filter(lambda sub: sub.is_ac(), subs))
    ac_subs.sort(key=lambda s: s.epoch_second)

    # 同一問題に複数のACがある場合は最新の提出を採用する。
    latest_ac_subs_dic = {}
    for sub in ac_subs:
        latest_ac_subs_dic[sub.problem_id] = sub

    return latest_ac_subs_dic.values()


def _get_sub_code(driver, contest_id, _id):
    ''' atcoder から提出コードを得る '''
    logger.debug("_get_sub_code()")
    url = f'https://atcoder.jp/contests/{contest_id}/submissions/{_id}'

    print("--------------------")
    print(f'url: {url}')
    print()

    driver.get(url)
    code = driver.find_element_by_id("submission-code")

    # code.text は提出時に含めていない空白が期待に反して含まれてしまう。
    # 空白はシンタックスハイライティングによるものであるように見える。
    # innerHTML から不要タグ等を消し、空白が意図通りのテキストを得る。
    inner_html = code.get_attribute('innerHTML')
    list_items = re.findall(r'<li[^>]*>.*?</li>', inner_html)
    lines = []
    for li in list_items:
        line1 = re.sub(r'<[^>]+>', '', li)
        line2 = re.sub(r'&nbsp;', '', line1)
        line3 = html.unescape(line2)
        lines.append(line3 + "\n")
    text = ''.join(lines)

    print(text)

    return text


def _get_file_path(problem_dir: Path, lang: str) -> Path:
    if "Python" in lang or "PyPy" in lang:
        return problem_dir / "Main.py"
    elif "Go" in lang:
        return problem_dir / "Main.go"
    else:
        raise f"不明な言語が指定された: {lang=}"


def _fetch_sub(
        sub: Submission, driver: WebDriver = None) -> tuple[WebDriver]:
    logger.debug("_fetch_sub()")
    # ディレクトリをコンテスト、問題ごとに作る。
    # 問題のディレクトリはa,b,cのようなアルファベット1文字ではなく、
    # problem_id をそのまま使う。
    # 理由はコンテストabsのように複数a問題が存在することがあるため。
    problem_dir = Path(DIR_SUBMISSION) / sub.contest_id / sub.problem_id
    problem_dir.mkdir(parents=True, exist_ok=True)

    # ファイルのパスを得る。
    file_path = _get_file_path(problem_dir, sub.language)
    metadata_path = problem_dir / 'metadata.json'

    # メタデータを読む。
    metadata = {}
    if metadata_path.exists():
        with open(str(metadata_path)) as f:
            metadata = json.load(f)

    # 既に提出コードがある場合は取得を取りやめる。
    if file_path.exists() and file_path.name in metadata:
        msub = Submission(metadata[file_path.name])
        if msub.id == sub.id:
            logger.debug("The path %s already exists. Skipped." % (
                file_path))
            return (driver, )
        logger.debug(f"{sub=}")
        logger.debug(f"{metadata_path=}")
        logger.debug(f"{metadata=}")

    # 提出ページへアクセスしてコードを得る。
    if driver is None:
        driver = webdriver.Chrome()
    sub_code = _get_sub_code(driver, sub.contest_id, sub.id)

    # コード、メタデータを保存する。
    with open(str(file_path), 'w') as f:
        f.write(sub_code)
    with open(str(metadata_path), 'w') as f:
        metadata[file_path.name] = sub
        _json_dump(metadata, f)

    # アクセス負荷軽減のために時間をおく。
    sleep(WAIT_SEC)

    return (driver,)


def _fetch_from_atcoder(
        subs: list[Submission]) -> None:
    ''' 提出のコードを得る '''
    logger.debug("_fetch_from_atcoder()")
    driver = None
    for sub in subs:
        driver, = _fetch_sub(sub, driver)
    if driver is not None:
        driver.quit()


def main(args):
    logger.debug("main()")

    # user_id を設定から読む。
    user_id = args.user_id
    if user_id is None:
        config_file = Path(DIR_SUBMISSION) / "config.toml"
        config = {}
        if config_file.exists():
            with open(config_file) as f:
                config = toml.load(f)
        config_atcoder = config.get("atcoder", {})
        user_id = config_atcoder.get("user_id", None)

    # 提出したACなコードを得て保存する。
    subs = _get_latest_ac_subs_from_atcoder_problems(user_id)
    _fetch_from_atcoder(subs)


if __name__ == '__main__':
    # 引数を解析する。
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    parser.add_argument('--user-id')
    args = parser.parse_args()

    # ロガーを設定する。
    if args.debug:
        handler = logging.StreamHandler()
        handler.setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        logger.propagate = False

    main(args)
