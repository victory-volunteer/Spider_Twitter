# -- coding: utf-8 --
import time, re, random
import asyncio, aiohttp
from datetime import datetime
import aiomysql
import requests

# Linux下写法
import uvloop

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Linux下写法
PROXYS = [

]

# window下做测试使用
# aiohttp只支持http, 写成https会报错
# PROXY = "http://127.0.0.1:7890"

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


async def get_guest_token(random_proxy):
    url = "https://api.twitter.com/1.1/guest/activate.json"
    payload = {}
    headers = {
        'authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
    }
    async with aiohttp.ClientSession() as session:
        # async with session.post(url, headers=headers, proxy=PROXY, data=payload) as resp:
        async with session.post(url, headers=headers, proxy=random_proxy, data=payload) as resp:
            result = await resp.json()
            try:
                HEADER['x-guest-token'] = result["guest_token"]
            except:
                print(f"设置x-guest-token时, 当前ip: {random_proxy}")
                print(result)


def formate_time2time_stamp(time_):
    # 将格式化后的时间转为时间戳
    return int(time.mktime(time.strptime(time_, "%Y-%m-%d")))


def time_stamp2formate_time(time_):
    # 将时间戳转为格式化后的时间
    return time.strftime("%Y-%m-%d", time.localtime(int(time_)))


def q_list_get(from_, since, until, condition):
    since_p = formate_time2time_stamp(since)  # 开始时间
    until_p = formate_time2time_stamp(until)  # 结束时间
    step = 60 * 60 * 24
    while (since_p < until_p):
        next = since_p + step
        # 增加关键字
        yield f'(from:{from_}) until:{time_stamp2formate_time(next)} since:{time_stamp2formate_time(since_p)} ({condition})'
        since_p = next


async def produce(queue, from_, since, until, condition):
    for q_ in q_list_get(from_, since, until, condition):
        await queue.put(q_)

    # 仅做测试
    # await queue.put('(from:drb_ra) until:2022-08-16 since:2022-08-15 (phishing OR tor OR c2 OR payload OR malware OR ransomware)')


# 批量抓取文件中的多个用户时使用
async def data_deal2(comment_text, publish_time, pool, user_name, article_id):
    """仅用来收集所有包含ip的推文信息"""
    obj = re.compile(
        "((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))((\[)?\.(])?((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))){3}")
    ret = obj.search(comment_text)
    if ret is None:
        return
    publish_time = datetime.strftime(datetime.strptime(publish_time, "%a %b %d %H:%M:%S +0000 %Y"), "%Y-%m-%d %H:%M:%S")

    with open('./data.txt', mode="a", encoding="utf-8") as fp:
        fp.write(f"{comment_text}\n{'-' * 20}{user_name}==={publish_time}==={article_id}\n")

    # 用来将c2和其它类型的区分开来
    # ret = re.search(r"(c2)\s", comment_text, re.I)
    # if ret:
    #     with open('./c2_data.txt', mode="a", encoding="utf-8") as fp:
    #         fp.write(f"{comment_text}\n{'-' * 20}{user_name}==={publish_time}==={article_id}\n")
    # else:
    #     with open('./other_data.txt', mode="a", encoding="utf-8") as fp:
    #         fp.write(f"{comment_text}\n{'-' * 20}{user_name}==={publish_time}==={article_id}\n")


async def data_deal1(comment_text, publish_time, pool, user_name, article_id):
    """正式处理推文信息"""
    comment_data = list()

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
    comment_data.append(type_)
    http_header = ret1.group(2)
    comment_data.append(http_header)
    ip_port = re.sub('[\[\]]', '', ret1.group(3))
    comment_data.append(ip_port)

    ret2 = obj2.search(comment_text)
    if ret2 is None:
        server = ''
        uri = ''
    else:
        server = re.sub('[\[\]]', '', ret2.group(2))
        uri = re.sub('[\[\]]', '', ret2.group(3).strip(','))
    comment_data.append(server)
    comment_data.append(uri)

    ret3 = obj3.search(comment_text)
    if ret3 is None:
        country = ''
    else:
        country = ret3.group(1)
    comment_data.append(country)

    ret4 = obj4.search(comment_text)
    if ret4 is None:
        asn = ''
    else:
        asn = ret4.group(1)
    comment_data.append(asn)

    ret5 = obj5.search(comment_text)
    if ret5 is None:
        host_header = ''
    else:
        host_header = re.sub('[\[\]]', '', ret5.group(1))
    comment_data.append(host_header)

    publish_time = datetime.strftime(datetime.strptime(publish_time, "%a %b %d %H:%M:%S +0000 %Y"), "%Y-%m-%d %H:%M:%S")
    comment_data.append(publish_time)
    global DATA_COUNT
    DATA_COUNT += 1
    # await database_deal1(comment_data, pool, user_name, article_id)
    # print(comment_data)
    # print("------------------------")


async def database_deal1(data, pool, user_name, article_id):
    async with pool.acquire() as conn:
        # print(id(conn), '-------------------')  # 用来验证mysql连接池是否重复利用
        async with conn.cursor() as cur:
            # 数据库操作
            try:
                sql = "insert into comments(user_name,user_url,article_url,type_,http_header,ip_port,server_,uri,country,asn,host_header,publish_time,save_time) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                user_url = f'https://twitter.com/{user_name}'
                article_url = f'{user_url}/status/{article_id}'
                time_ = time.strftime('%Y-%m-%d %H:%M:%S')
                await cur.execute(sql, (
                    user_name, user_url, article_url, data[0], data[1], data[2], data[3], data[4], data[5], data[6],
                    data[7], data[8], time_))
                await conn.commit()
            except Exception as result:
                await conn.rollback()
                print(f"数据写入出错: {result}")


async def data_deal(comment_text, publish_time, pool, user_name, article_id):
    """正式处理推文信息"""

    comment_text = re.sub('\[|]', '', comment_text)

    type_ = ''
    type_set = set()
    ret0 = re.finditer(r"(phishing|tor|c2|payload|malware|ransomware)", comment_text, flags=re.I)
    for i in ret0:
        type_set.add(f'{i.group(1).lower()}')
    type_list = list(type_set)
    # 拼接
    for i in type_list:
        type_ += f'{i}, '
    type_ = type_.strip(', ')
    if type_ == '':
        return

    url = ''
    t_co_link = ''
    # 匹配以(h(xx|tt)p(s)?)开头的; 以(\s/)开头的; 以(\sip/)开头的; 以(\s域名/)开头的;
    ret5 = re.compile(
        r'''(((([hH](xx|XX)?(xx|tt|XX|TT)[pP][sS]?)?://[-a-zA-Z0-9./:?&=_~#@!]+?)|(\s/[-a-zA-Z0-9./:?&=_~#@!]+?)|(\s((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))(\.((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))){3}/[-a-zA-Z0-9./:?&=_~#@!]+?)|(\s([^\[\]'"><. :/\n]+\.)+[a-zA-Z]+/[-a-zA-Z0-9./:?&=_~#@!]+?)))[,;]?\s''',
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
        r"((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))(\.((2((5[0-5])|([0-4]\d)))|([0-1]?\d{1,2}))){3}([:/][{(]? ?(\d{1,5}(, |,)?)+ ?[})]?)?")
    ip_set = set()
    it = ret2.finditer(comment_text)
    # 去重
    for i in it:
        ip_set.add(f'{i.group()}')
    ip_list = list(ip_set)
    # 拼接
    for i in ip_list:
        ip += f'{i}, '
    ip = ip.strip(', ')

    # 去除干扰项
    comment_text = re.sub(ret5, '', comment_text)
    comment_text = re.sub(ret2, '', comment_text)

    # print(comment_text)

    port = ''
    ret3 = re.finditer(r'Ports?:? ?((\d{1,5}(, |,)?)+)\s', comment_text, flags=re.I)
    for i in ret3:
        port += f'{i.group(1)}, '
    ret4 = re.finditer(r'(\d{1,5}/(tcp|udp))\s', comment_text, flags=re.I)
    for i in ret4:
        port += f'{i.group(1)}, '
    port = port.strip(', ')

    # 主域和子域混在一起, 更加简单
    domain = ''
    ret = re.finditer(r'''(([^\[\]'"><. :/\n]+\.)+[a-zA-Z]+)[,\s]''', comment_text, flags=re.I)
    for i in ret:
        domain += f'{i.group(1)}, '
    domain = domain.strip(', ')

    ret4 = re.search('Target: (.*)', comment_text, flags=re.I)
    if ret4 is None:
        target = ''
    else:
        target = ret4.group(1)

    hash_type = ''
    hash_value = ''
    ret5 = re.compile(
        r"([:\s]|^)((?P<md5_16>[a-fA-F\d]{16})|(?P<md5_32>[a-fA-F\d]{32})|(?P<sha1>[a-fA-F\d]{40})|(?P<sha224>[a-fA-F\d]{56})|(?P<sha256>[a-fA-F\d]{64})|(?P<sha384>[a-fA-F\d]{96})|(?P<sha512>[a-fA-F\d]{128})|(?P<other>[a-fA-F\d]{129,512}))[,;]?\s",re.I)
    it = ret5.finditer(comment_text)
    for i in it:
        for key, value in i.groupdict().items():
            if value is not None:
                hash_type += f'{key}, '
                hash_value += f'{value}, '
    hash_type = hash_type.strip(', ')
    hash_value = hash_value.strip(', ')

    # ----------匹配ASN----------
    # 不可通用, 仅可匹配特殊推文中的内容
    # ret6 = re.search(r'\((.*?)\)', comment_text)
    # if ret6 is None:
    #     asn = ''
    # else:
    #     asn = ret6.group(1)
    # ----------匹配ASN----------

    # data_list = [type_, domain, ip, port, url, t_co_link, target, hash_type, hash_value]
    # print(f"{data_list}\n{'-' * 20}")
    # await database_deal(user_name, article_id, type_, domain, ip, port, url, t_co_link, target, hash_type, hash_value, publish_time, pool)


async def database_deal(user_name, article_id, type_, domain, ip, port, url, t_co_link, target, hash_type, hash_value,
                        publish_time, pool):
    async with pool.acquire() as conn:
        # print(id(conn), '-------------------')  # 用来验证mysql连接池是否重复利用
        async with conn.cursor() as cur:
            # 数据库操作
            try:
                sql = "insert into others(user_name,user_url,article_url,type_,domain,ip,port,url,t_co_link,target,hash_type,hash_value,publish_time,save_time) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                user_url = f'https://twitter.com/{user_name}'
                article_url = f'{user_url}/status/{article_id}'
                time_ = time.strftime('%Y-%m-%d %H:%M:%S')
                publish_time = datetime.strftime(datetime.strptime(publish_time, "%a %b %d %H:%M:%S +0000 %Y"),
                                                 "%Y-%m-%d %H:%M:%S")
                await cur.execute(sql, (
                    user_name, user_url, article_url, type_, domain, ip, port, url, t_co_link, target, hash_type,
                    hash_value, publish_time, time_))
                await conn.commit()
            except Exception as result:
                await conn.rollback()
                print(f"数据写入出错: {result}")


async def get_comment(q, pool, error_file, user_name):
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
            "include_entities": "true",
            "include_user_entities": "true",
            "include_ext_media_color": "true",
            "include_ext_media_availability": "true",
            "include_ext_sensitive_media_warning": "true",
            "include_ext_trusted_friends_metadata": "true",
            "send_error_codes": "true",
            "simple_quoted_tweet": "true",
            "q": f"{q}",
            "count": "20",
            "query_source": "typed_query",
            "pc": "1",
            "spelling_corrections": "1",
            "include_ext_edit_control": "true",
            "ext": "mediaStats,highlightedLabel,hasNftAvatar,voiceInfo,enrichments,superFollowMetadata,unmentionInfo,editControl,collab_control,vibe"
        }
        url = "https://api.twitter.com/2/search/adaptive.json"
        global ERROR_COUNT
        async with aiohttp.ClientSession() as session:
            while True:
                # 最好使用同一个代理, 防止出现"Forbidden."的错误
                random_proxy = f""

                # 防止x-guest-token过期和发生"Rate limit exceeded"错误, 每次请求都在这里重新设置一下
                await get_guest_token(random_proxy)
                # async with session.get(url, headers=HEADER, proxy=PROXY, params=param) as resp:
                async with session.get(url, headers=HEADER, proxy=random_proxy, params=param) as resp:
                    ret2 = re.match(r'^\{"errors":\[\{"message":"Rate limit exceeded","code":88}]}$', await resp.text())
                    if ret2 is not None:
                        with open(error_file, mode="a", encoding="utf-8") as fp:
                            fp.write(f"{q}\n")
                        ERROR_COUNT += 1
                        break

                    root = await resp.json()
                    try:
                        tweets = root['globalObjects']['tweets']
                    except:
                        print(f"{'-' * 40}{q}")
                        print(f"当前ip: {random_proxy}")
                        print(root)
                        return
                    if not tweets:
                        break
                    for key, value in tweets.items():
                        global COMMENTS_COUNT
                        COMMENTS_COUNT += 1
                        await data_deal(value['full_text'], value['created_at'], pool, user_name, key)

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
    except Exception as e:
        print(f"请求{q}时, 出错: {e}")
        print(f"当前ip: {random_proxy}")


async def consume(queue, pool, error_file, user_name):
    while True:
        twitter_time = await queue.get()
        await get_comment(twitter_time, pool, error_file, user_name)
        queue.task_done()


async def run(from_, since, until, error_file, user_name, condition):
    queue = asyncio.Queue(maxsize=1000)  # 这里不设置容量也可以
    pool = await aiomysql.create_pool(
        host="xxx",
        port=3306,
        user='xxx',
        password='xxx',
        db='twitter',
        minsize=1,
        maxsize=10,
    )

    # 这里相当于500个并发, 所以最大会同时设置500次x-guest-token值
    # 解决方法: 在程序开始时, 就先设置一次x-guest-token值
    random_proxy = f""
    await get_guest_token(random_proxy)
    tasks = [asyncio.create_task(consume(queue, pool, error_file, user_name)) for _ in range(500)]
    await produce(queue, from_, since, until, condition)
    await queue.join()
    for c in tasks:
        c.cancel()


async def first_judgment(from_, since, until, user_name, condition):
    q = f'(from:{from_}) until:{until} since:{since} ({condition})'
    pool = await aiomysql.create_pool(
        host="xx",
        port=3306,
        user='xx',
        password='xx',
        db='twitter',
        minsize=1,
        maxsize=10,
    )
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
        "include_entities": "true",
        "include_user_entities": "true",
        "include_ext_media_color": "true",
        "include_ext_media_availability": "true",
        "include_ext_sensitive_media_warning": "true",
        "include_ext_trusted_friends_metadata": "true",
        "send_error_codes": "true",
        "simple_quoted_tweet": "true",
        "q": f"{q}",
        "count": "20",
        "query_source": "typed_query",
        "pc": "1",
        "spelling_corrections": "1",
        "include_ext_edit_control": "true",
        "ext": "mediaStats,highlightedLabel,hasNftAvatar,voiceInfo,enrichments,superFollowMetadata,unmentionInfo,editControl,collab_control,vibe"
    }

    url = "https://api.twitter.com/2/search/adaptive.json"
    async with aiohttp.ClientSession() as session:
        # 最好使用同一个代理, 防止出现"Forbidden."的错误
        random_proxy = f"http://location.xx"

        # 防止x-guest-token过期和发生"Rate limit exceeded"错误, 每次请求都在这里重新设置一下
        await get_guest_token(random_proxy)
        async with session.get(url, headers=HEADER, proxy=random_proxy, params=param) as resp:
            root = await resp.json()
            tweets = root['globalObjects']['tweets']
            article_count = len(tweets)
            if article_count == 0:
                print(f"用户{user_name}数据为{article_count}")
                return
            elif article_count <= 10:
                print(f"用户{user_name}数据为{article_count}")
                for key, value in tweets.items():
                    await data_deal(value['full_text'], value['created_at'], pool, user_name, key)
            else:
                return True


def main(user_name):
    start = time.time()

    # 测试数据:
    from_ = f'{user_name}'  # 用户名
    since = '2022-01-01'  # 开始时间
    # until = '2022-01-02'  # 结束时间
    until = '2023-01-10'  # 结束时间
    condition = 'phishing OR tor OR c2 OR payload OR malware OR ransomware'  # 搜索条件
    error_file = './error_data.txt'

    # 先直接获取一年内的所有推文, 判断是否小于10条
    sign = asyncio.run(first_judgment(from_, since, until, user_name, condition))
    if sign:
        print(f"用户{from_}数据大于10条, 有价值逐天抓取")

        # loop = asyncio.get_event_loop()
        # loop.run_until_complete(run(from_, since, until, error_file, user_name, condition))

        # linux或mac这样写
        asyncio.run(run(from_, since, until, error_file, user_name, condition))

        print(f"评论总量: {COMMENTS_COUNT} 有效数据: {DATA_COUNT} 写入{error_file}的错误数据: {ERROR_COUNT}")

    end = time.time()
    print(f"用户{user_name}耗时: {end - start}")


if __name__ == '__main__':
    main('KesaGataMe0')

    # 批量抓取文件中的多个用户时使用
    # obj = re.compile(r'^@(.*?)\s')
    # with open('./names.txt', mode="r", encoding="utf-8") as fp:
    #     count = 0
    #     for line in fp:
    #         count += 1
    #         ret = obj.match(line.strip())
    #         name = ret.group(1)
    #         print(f"{'-' * 30}{name}")
    #         main(name)
    #         # if count == 1:
    #         #     break
    #     print(f"本次读取: {count}行")

# linux后台运行: nohup python3.8 -u test.py >dns.log 2>&1 &