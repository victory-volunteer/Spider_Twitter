# -- coding: utf-8 --
import time, re, random
import schedule
from datetime import datetime
import pymysql
import requests
import threading
from concurrent.futures import ThreadPoolExecutor
from dbutils.pooled_db import PooledDB

# Linux下写法
PROXYS = [
  
]

HEADER = {
    'x-twitter-client-language': 'zh-cn',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36',
    'accept-language': 'zh-CN,zh;q=0.9',
    'referer': 'https://twitter.com/',
    'x-guest-token': '1607946257955489073',  # 这里先随便设一个值, 方便后面程序捕获错误并重新设值
    'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
}

COMMENTS_COUNT = 0  # 统计获取推文的总条数
DATA_COUNT = 0  # 统计有效数据的总条数
ERROR_COUNT = 0  # 统计发生'Rate limit exceeded'错误的条数


def formate_time2time_stamp(time_):
    # 将格式化后的时间转为时间戳
    return int(time.mktime(time.strptime(time_, "%Y-%m-%d")))


def time_stamp2formate_time(time_):
    # 将时间戳转为格式化后的时间
    return time.strftime("%Y-%m-%d", time.localtime(int(time_)))


def q_list_get(from_, since, until):
    since_p = formate_time2time_stamp(since)  # 开始时间
    until_p = formate_time2time_stamp(until)  # 结束时间
    step = 60 * 60 * 24
    while (since_p < until_p):
        next = since_p + step
        # 增加关键字
        yield f'(from:{from_}) until:{time_stamp2formate_time(next)} since:{time_stamp2formate_time(since_p)}'
        since_p = next


def get_guest_token(random_proxy):
    url = "https://api.twitter.com/1.1/guest/activate.json"
    payload = {}
    headers = {
        'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
    }
    resp = requests.post(url, headers=headers, proxies=random_proxy, data=payload)
    result = resp.json()
    try:
        HEADER['x-guest-token'] = result["guest_token"]
    except:
        # 抛出此错误时, 仅代表获取x-guest-token参数的这个请求出错, 实际无关紧要, 并不影响后面数据的准确性(只有在解析数据时出错才影响后面数据)
        print(f"设置x-guest-token时, 当前ip: {random_proxy}")
        print(result)
    resp.close()


def get_comment(q_, user_name, RLock, error_file, pool):
    try:
        param = {
            "include_profile_interstitial_type": "1",
            "include_blocking": "1",
            "include_blocked_by": "1",
            "include_followed_by": "1",
            "include_want_retweets": "1",
            "include_mute_edge": "1",
            "include_can_dm": "1",
            "include_can_media_tag": "1",
            "include_ext_has_nft_avatar": "1",
            "include_ext_is_blue_verified": "1",
            "include_ext_verified_type": "1",
            "skip_status": "1",
            "cards_platform": "Web-12",
            "include_cards": "1",
            "include_ext_alt_text": "true",
            "include_ext_limited_action_results": "false",
            "include_quote_count": "true",
            "include_reply_count": "1",
            "tweet_mode": "extended",
            "include_ext_collab_control": "true",
            "include_ext_views": "true",
            "include_entities": "true",
            "include_user_entities": "true",
            "include_ext_media_color": "true",
            "include_ext_media_availability": "true",
            "include_ext_sensitive_media_warning": "true",
            "include_ext_trusted_friends_metadata": "true",
            "send_error_codes": "true",
            "simple_quoted_tweet": "true",
            "q": f"{q_}",
            "tweet_search_mode": "live",
            "count": "20",
            "query_source": "typed_query",
            "pc": "1",
            "spelling_corrections": "1",
            "include_ext_edit_control": "true",
            "ext": "mediaStats,highlightedLabel,hasNftAvatar,voiceInfo,enrichments,superFollowMetadata,unmentionInfo,editControl,collab_control,vibe"
        }
        url = "https://api.twitter.com/2/search/adaptive.json"
        global ERROR_COUNT
        while True:
            random_ip = random.choice(PROXYS)
            random_proxy = {
                "http": f" ",
                "https": f" "
            }
            get_guest_token(random_proxy)
            resp = requests.get(url, headers=HEADER, proxies=random_proxy, params=param)
            ret2 = re.match(r'^\{"errors":\[\{"message":"Rate limit exceeded","code":88}]}$', resp.text)
            if ret2 is not None:
                RLock.acquire()
                with open(error_file, mode="a", encoding="utf-8") as fp:
                    fp.write(f"{q_}\n")
                ERROR_COUNT += 1
                RLock.release()
                break
            root = resp.json()
            try:
                tweets = root['globalObjects']['tweets']
            except:
                print(f"{'-' * 40}{q_}")
                print(f"当前ip: {random_proxy}")
                print(root)
                return
            if not tweets:
                break
            for key, value in tweets.items():
                global COMMENTS_COUNT
                RLock.acquire()
                COMMENTS_COUNT += 1
                RLock.release()
                data_deal(value['full_text'], value['created_at'], user_name, key, RLock, pool)

            next = root.get('timeline', {}).get('instructions', [])
            if len(next) > 1:
                cursor = next[-1].get('replaceEntry', {}).get('entry', {}).get('content', {}).get('operation',
                                                                                                  {}).get(
                    'cursor',
                    {}).get(
                    'value', '')
            else:
                cursor = next[0].get('addEntries', {}).get('entries', [{}])[-1].get('content', {}).get(
                    'operation',
                    {}).get(
                    'cursor', {}).get('value', '')
            if not cursor:
                cursor = ''
            param['cursor'] = cursor
            resp.close()
    except Exception as e:
        print(f"请求{q_}时, 出错: {e}")
        print(f"当前ip: {random_proxy}")


def data_deal(comment_text, publish_time, user_name, article_id, lock, pool):
    comment_text = re.sub('\[|]', '', comment_text)
    global DATA_COUNT

    if user_name == 'PhishStats':
        obj = re.compile(r''' at (.*?) #''')
        ret = obj.search(comment_text)
        if ret is not None:
            # 先确定类型
            type_ = ''
            type_set = set()
            ret0 = re.finditer(
                r"(C2|Cobalt\s?Strike|Phishing|phish|Async\s?RAT|Phoenix\s?RAT|ASync\s?RAT|Attacker\s?IP|IoT|blacklist|IoC|Payloads|Qakbot|Baza\s?Loader|Emotet|scammers|scam|フィッシングメール|フィッシング詐欺|フィッシング|virut|botnet|Port\s?Scanning|Corta\s?Bot|DGA|cyberattacks|Malware|malicious|ransomware|Bruteforce|honeypot|executemalware|Raccoon\s?Stealer|Smoke\s?Loader|Icarus|bazaar|IOC's|spammers|cryptbot|Iced\s?ID|Warzone\s?RAT|Side\s?Winder|Vile\s?RAT|tor|payload|IOC|Indicators\s?of\s?Compromise|Trojans|worm|spyware|Threat\s?Intelligence|APT)(\d+|:)?(\s|$)",
                comment_text, flags=re.I)
            for i in ret0:
                type_set.add(f'{i.group(1).lower()}')
            type_list = list(type_set)
            for i in type_list:
                type_ += f'{i}, '
            type_ = type_.strip(', ')
            if type_ == '':
                return

            data = ret.group(1)
            list_data = data.split('|')
            url = list_data[0].strip()
            url = re.sub('[hH](xx|XX)?(xx|tt|XX|TT)[pP]', 'http', url, flags=re.I)
            ip = list_data[1].strip()
            country = list_data[2].strip()
            company = list_data[3].strip()
            asn = list_data[4].strip()

            lock.acquire()
            DATA_COUNT += 1
            lock.release()
            database_deal_PhishStats(user_name, article_id, type_, url, ip, country, company, asn, publish_time, pool)
        return
    elif user_name == 'drb_ra':

        obj1 = re.compile(r'(C2): (HTTP[S]?) @ (.*)')
        obj2 = re.compile(r'C2 Server( #\d*)?: ([/]?.*?)([/,].*)')
        obj3 = re.compile(r'Country: (.*)')
        obj4 = re.compile(r'ASN: (.*)')
        obj5 = re.compile(r'Host Header: (.*)')

        # 第一个解析的ip和端口必须有, 否则直接返回
        ret1 = obj1.search(comment_text)
        if ret1 is None:
            return
        type_ = ret1.group(1)
        http_header = ret1.group(2)
        ip_port = re.sub('[\[\]]', '', ret1.group(3))

        ret2 = obj2.search(comment_text)
        if ret2 is None:
            server = ''
            uri = ''
        else:
            server = re.sub('[\[\]]', '', ret2.group(2))
            uri = re.sub('[\[\]]', '', ret2.group(3).strip(','))

        ret3 = obj3.search(comment_text)
        if ret3 is None:
            country = ''
        else:
            country = ret3.group(1)

        ret4 = obj4.search(comment_text)
        if ret4 is None:
            asn = ''
        else:
            asn = ret4.group(1)

        ret5 = obj5.search(comment_text)
        if ret5 is None:
            host_header = ''
        else:
            host_header = re.sub('[\[\]]', '', ret5.group(1))

        lock.acquire()
        DATA_COUNT += 1
        lock.release()
        database_deal_drb_ra(user_name, article_id, type_, http_header, ip_port, server, uri, country, asn, host_header,
                             publish_time, pool)
        return

    obj1 = re.compile(
        "((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))((\[)?\.(])?((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))){3}")
    obj2 = re.compile(r'''(([^\[\]()#'"><. :/\n]+\.)+[a-zA-Z]+)[,\s]''', re.I)
    ret = obj1.search(comment_text)
    if ret is None:
        ret = obj2.search(comment_text)
        if ret is None:
            return

    type_ = ''
    type_set = set()
    ret0 = re.finditer(
        r"(C2|Cobalt\s?Strike|Phishing|phish|Async\s?RAT|Phoenix\s?RAT|ASync\s?RAT|Attacker\s?IP|IoT|blacklist|IoC|Payloads|Qakbot|Baza\s?Loader|Emotet|scammers|scam|フィッシングメール|フィッシング詐欺|フィッシング|virut|botnet|Port\s?Scanning|Corta\s?Bot|DGA|cyberattacks|Malware|malicious|ransomware|Bruteforce|honeypot|executemalware|Raccoon\s?Stealer|Smoke\s?Loader|Icarus|bazaar|IOC's|spammers|cryptbot|Iced\s?ID|Warzone\s?RAT|Side\s?Winder|Vile\s?RAT|tor|payload|IOC|Indicators\s?of\s?Compromise|Trojans|worm|spyware|Threat\s?Intelligence|APT)(\d+|:)?(\s|$)",
        comment_text, flags=re.I)
    for i in ret0:
        type_set.add(f'{i.group(1).lower()}')
    type_list = list(type_set)
    for i in type_list:
        type_ += f'{i}, '
    type_ = type_.strip(', ')
    if type_ == '':
        return
    if 'apt' in type_set:
        # print(type_)
        lock.acquire()
        DATA_COUNT += 1
        lock.release()
        # print("遇到apt, 直接保存")
        apt_database_deal(user_name, article_id, type_, comment_text, publish_time, pool)
        return

    url = ''
    t_co_link = ''
    ret5 = re.compile(
        r'''((((([hH](xx|XX)?(xx|tt|XX|TT)[pP][sS]?)|ftp)?://[-a-zA-Z0-9./:?&=_~#@!]+?)|(\s/[-a-zA-Z0-9./:?&=_~#@!]+?)|(\s((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))(\.((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))){3}/[-a-zA-Z0-9./:?&=_~#@!]+?)|(\s([^\[\]'"><. :/\n]+\.)+[a-zA-Z]+/[-a-zA-Z0-9./:?&=_~#@!]+?)))[,;]?(\s|$)''',
        re.I)
    it = ret5.finditer(comment_text)
    for i in it:
        sub0 = re.sub('[hH](xx|XX)?(xx|tt|XX|TT)[pP]', 'http', i.group(1), flags=re.I)
        sub0 = sub0.strip()
        if i.group(1)[-1] == '.':
            continue
        elif len(i.group(1)) == 1:
            continue
        elif re.search(r"//t.co/", sub0, flags=re.I):
            t_co_link += f'{sub0}, '
            continue
        url += f'{sub0}, '
    url = url.strip(', ')
    t_co_link = t_co_link.strip(', ')

    ip = ''
    ret2 = re.compile(
        r"((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))(\.((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))){3}([:/#][{(]? ?(\d{1,5}(, |,)?)+ ?[})]?)?")
    ip_set = set()
    it = ret2.finditer(comment_text)
    for i in it:
        ip_set.add(f'{i.group()}')
    ip_list = list(ip_set)
    for i in ip_list:
        ip += f'{i}, '
    ip = ip.strip(', ')

    # 去除干扰项
    comment_text = re.sub(ret5, '', comment_text)
    comment_text = re.sub(ret2, '', comment_text)

    # print(comment_text)

    port = ''
    ret3 = re.finditer(r'Ports?\s?(Scanning)?:? ?((\d{1,5}(, |,)?)+)\s', comment_text, flags=re.I)
    for i in ret3:
        port += f'{i.group(2)}, '
    ret4 = re.finditer(r'(\d{1,5}/(tcp|udp))\s', comment_text, flags=re.I)
    for i in ret4:
        port += f'{i.group(1)}, '
    port = port.strip(', ')

    domain = ''
    ret = re.finditer(r'''(([^\[\]()#'"><. :/\n]+\.)+[a-zA-Z]+)[,\s]''', comment_text, flags=re.I)
    for i in ret:
        domain += f'{i.group(1)}, '
    domain = domain.strip(', ')

    ret4 = re.search('Target:?\s(.*)', comment_text, flags=re.I)
    if ret4 is None:
        target = ''
    else:
        target = ret4.group(1)

    hash_type = ''
    hash_value = ''
    obj3 = re.compile(r'Sample[s]?\s?on\s?VT', re.I)
    ret = obj3.search(comment_text)
    if ret is not None:
        ret5 = re.compile(
            r"([:\s]|^)((?P<md5_32>[a-f\d]{32})|(?P<sha1>[a-f\d]{40})|(?P<sha256>[a-f\d]{64}))[,;]?\s", )
        it = ret5.finditer(comment_text)
        for i in it:
            for key, value in i.groupdict().items():
                if value is not None:
                    hash_type += f'{key}, '
                    hash_value += f'{value}, '
        hash_type = hash_type.strip(', ')
        hash_value = hash_value.strip(', ')

    # ----------匹配ASN----------
    if user_name == 'KesaGataMe0':
        asn = ''
        ret = re.search(r'\((.*?)\)', comment_text)
        if ret is not None:
            asn = ret.group(1)
    else:
        asn = ''
        ret6 = re.search(r'ASN(: | |:)(.*?)\s', comment_text, flags=re.I)
        if ret6 is not None:
            asn = ret6.group(2)
    # ----------匹配ASN----------

    lock.acquire()
    DATA_COUNT += 1
    lock.release()
    database_deal(user_name, article_id, type_, domain, ip, port, url, t_co_link, target, hash_type, hash_value,
                  asn, publish_time, pool)

    # data_list = [type_, domain, ip, port, url, t_co_link, target, hash_type, hash_value,asn]
    # print(f"{data_list}\n{'-' * 20}")


def database_deal(user_name, article_id, type_, domain, ip, port, url, t_co_link, target, hash_type, hash_value,
                  asn, publish_time, pool):
    con = pool.connection()
    cur = con.cursor()
    sql = "insert into others(user_name,user_url,article_url,type_,domain,ip,port,url,t_co_link,target,hash_type,hash_value,asn,publish_time,save_time) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    user_url = f'https://twitter.com/{user_name}'
    article_url = f'{user_url}/status/{article_id}'
    publish_time = datetime.strftime(datetime.strptime(publish_time, "%a %b %d %H:%M:%S +0000 %Y"),
                                     "%Y-%m-%d %H:%M:%S")
    time_ = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        cur.execute(sql, (
            user_name, user_url, article_url, type_, domain, ip, port, url, t_co_link, target, hash_type,
            hash_value, asn, publish_time, time_))
        con.commit()
    except Exception as result:
        con.rollback()
        print(f"数据写入出错: {result}")
    finally:
        cur.close()
        con.close()


def database_deal_PhishStats(user_name, article_id, type_, url, ip, country, company, asn, publish_time, pool):
    con = pool.connection()
    cur = con.cursor()
    sql = "insert into others(user_name,user_url,article_url,type_,url,ip,country,company,asn,publish_time,save_time) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    user_url = f'https://twitter.com/{user_name}'
    article_url = f'{user_url}/status/{article_id}'
    publish_time = datetime.strftime(datetime.strptime(publish_time, "%a %b %d %H:%M:%S +0000 %Y"),
                                     "%Y-%m-%d %H:%M:%S")
    time_ = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        cur.execute(sql, (
            user_name, user_url, article_url, type_, url, ip, country, company, asn, publish_time, time_))
        con.commit()
    except Exception as result:
        con.rollback()
        print(f"数据写入出错: {result}")
    finally:
        cur.close()
        con.close()


def database_deal_drb_ra(user_name, article_id, type_, http_header, ip_port, server, uri, country, asn, host_header,
                         publish_time, pool):
    con = pool.connection()
    cur = con.cursor()
    sql = "insert into c2_1(user_name,user_url,article_url,type_,http_header,ip_port,server_,uri,country,asn,host_header,publish_time,save_time) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    user_url = f'https://twitter.com/{user_name}'
    article_url = f'{user_url}/status/{article_id}'
    publish_time = datetime.strftime(datetime.strptime(publish_time, "%a %b %d %H:%M:%S +0000 %Y"),
                                     "%Y-%m-%d %H:%M:%S")
    time_ = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        cur.execute(sql, (
            user_name, user_url, article_url, type_, http_header, ip_port, server, uri, country, asn, host_header,
            publish_time, time_))
        con.commit()
    except Exception as result:
        con.rollback()
        print(f"数据写入出错: {result}")
    finally:
        cur.close()
        con.close()


def apt_database_deal(user_name, article_id, type_, apt_article, publish_time, pool):
    con = pool.connection()
    cur = con.cursor()
    sql = "insert into others(user_name,user_url,article_url,type_,apt_article,publish_time,save_time) values(%s,%s,%s,%s,%s,%s,%s)"
    user_url = f'https://twitter.com/{user_name}'
    article_url = f'{user_url}/status/{article_id}'
    publish_time = datetime.strftime(datetime.strptime(publish_time, "%a %b %d %H:%M:%S +0000 %Y"),
                                     "%Y-%m-%d %H:%M:%S")
    time_ = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        cur.execute(sql, (
            user_name, user_url, article_url, type_, apt_article, publish_time, time_))
        con.commit()
    except Exception as result:
        con.rollback()
        print(f"数据写入出错: {result}")
    finally:
        cur.close()
        con.close()


def run(q_, user_name, RLock, error_file, pool):
    get_comment(q_, user_name, RLock, error_file, pool)


def first_judgment(from_, since, until, user_name, RLock, error_file, pool):
    q_ = f'(from:{from_}) until:{until} since:{since}'
    try:
        param = {
            "include_profile_interstitial_type": "1",
            "include_blocking": "1",
            "include_blocked_by": "1",
            "include_followed_by": "1",
            "include_want_retweets": "1",
            "include_mute_edge": "1",
            "include_can_dm": "1",
            "include_can_media_tag": "1",
            "include_ext_has_nft_avatar": "1",
            "include_ext_is_blue_verified": "1",
            "include_ext_verified_type": "1",
            "skip_status": "1",
            "cards_platform": "Web-12",
            "include_cards": "1",
            "include_ext_alt_text": "true",
            "include_ext_limited_action_results": "false",
            "include_quote_count": "true",
            "include_reply_count": "1",
            "tweet_mode": "extended",
            "include_ext_collab_control": "true",
            "include_ext_views": "true",
            "include_entities": "true",
            "include_user_entities": "true",
            "include_ext_media_color": "true",
            "include_ext_media_availability": "true",
            "include_ext_sensitive_media_warning": "true",
            "include_ext_trusted_friends_metadata": "true",
            "send_error_codes": "true",
            "simple_quoted_tweet": "true",
            "q": f"{q_}",
            "tweet_search_mode": "live",
            "count": "20",
            "query_source": "typed_query",
            "pc": "1",
            "spelling_corrections": "1",
            "include_ext_edit_control": "true",
            "ext": "mediaStats,highlightedLabel,hasNftAvatar,voiceInfo,enrichments,superFollowMetadata,unmentionInfo,editControl,collab_control,vibe"
        }
        url = "https://api.twitter.com/2/search/adaptive.json"
        global ERROR_COUNT
        random_ip = random.choice(PROXYS)
        random_proxy = {
            "http": f"",
            "https": f" "
        }
        get_guest_token(random_proxy)
        resp = requests.get(url, headers=HEADER, proxies=random_proxy, params=param)
        ret2 = re.match(r'^\{"errors":\[\{"message":"Rate limit exceeded","code":88}]}$', resp.text)
        if ret2 is not None:
            RLock.acquire()
            with open(error_file, mode="a", encoding="utf-8") as fp:
                fp.write(f"{q_}\n")
            ERROR_COUNT += 1
            RLock.release()
        root = resp.json()
        try:
            tweets = root['globalObjects']['tweets']
        except:
            print(f"{'-' * 40}{q_}")
            print(f"当前ip: {random_proxy}")
            print(root)
            return
        article_count = len(tweets)
        if article_count == 0:
            print(f"用户{user_name}数据为{article_count}")
            return
        elif article_count <= 10:
            print(f"用户{user_name}数据为{article_count}")
            for key, value in tweets.items():
                global COMMENTS_COUNT
                RLock.acquire()
                COMMENTS_COUNT += 1
                RLock.release()
                data_deal(value['full_text'], value['created_at'], user_name, key, RLock, pool)
        else:
            return True
        resp.close()
    except Exception as e:
        print(f"请求{q_}时, 出错: {e}")
        print(f"当前ip: {random_proxy}")


def main(user_name):
    start = time.time()

    # 测试数据:
    from_ = f'{user_name}'  # 用户名

    # 统计一年的
    # since = '2022-01-01'  # 开始时间
    # until = '2023-02-01'  # 结束时间
    # 统计每天的
    until = time.strftime('%Y-%m-%d')
    since = time.strftime("%Y-%m-%d", time.localtime(int(int(time.mktime(time.strptime(until, "%Y-%m-%d"))) - 60 * 60 * 24)))

    error_file = './error_data.txt'

    RLock = threading.RLock()

    maxconnections = 10  # 最大连接数
    pool = PooledDB(
        pymysql,
        maxconnections,
        host="xx",
        user='xx',
        port=3306,
        passwd='xx',
        db='twitter',
        use_unicode=True)

    # 先直接获取一年内的所有推文, 判断是否小于10条
    sign = first_judgment(from_, since, until, user_name, RLock, error_file, pool)
    if sign:
        print(f"用户{from_}数据大于10条, 有价值逐天抓取")
        with ThreadPoolExecutor(80) as t:
            for q_ in q_list_get(from_, since, until):
                t.submit(run, q_, user_name, RLock, error_file, pool)
    print(f"评论总量: {COMMENTS_COUNT} 写入{error_file}的错误数据: {ERROR_COUNT} 有效数据: {DATA_COUNT}")
    if DATA_COUNT == 0:
        with open('./names_flag.txt', mode="a", encoding="utf-8") as fp:
            fp.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}------{user_name}\n")

    end = time.time()
    print(f"用户{user_name}耗时: {end - start}")


def timed_task():
    # main('CujoaiLabs')

    # 批量抓取文件中的多个用户时使用
    obj = re.compile(r'^@(.*)')
    with open('./names.txt', mode="r", encoding="utf-8") as fp:
        count = 0
        for line in fp:
            count += 1
            ret = obj.match(line.strip())
            user_name = ret.group(1)
            print(f"{'-' * 30}{user_name}")

            # 重新赋值全局变量, 防止污染
            global COMMENTS_COUNT, DATA_COUNT, ERROR_COUNT
            COMMENTS_COUNT = 0
            DATA_COUNT = 0
            ERROR_COUNT = 0
            main(user_name)
            # if count == 1:
            #     break
        print(f"本次读取: {count}行")


if __name__ == '__main__':
    # timed_task()

    # 每天定时执行
    schedule.every().day.at("00:30").do(timed_task)
    while True:
        schedule.run_pending()
        time.sleep(1)

# linux后台运行: nohup python3.8 -u test.py >dns.log 2>&1 &
