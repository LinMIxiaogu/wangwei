"""
本地动态配置：示例热词与热榜标题

用于在流式事件中进行随机抽样展示，避免依赖实时接口。
"""

# 示例热词（多城市混合）
LOCAL_XHS_HOT_KEYWORDS = [
    # 北京
    "王府井citywalk路线",
    "北京路线",
    "北京旅游路线",
    "北京美食探店",
    "故宫游玩攻略",
    "颐和园一日游",
    "南锣鼓巷美食",
    "什刹海划船",
    "北京拍照圣地",
    "北京亲子游",
    # 杭州
    "杭州路线",
    "杭州西湖游玩攻略",
    "西湖十景打卡",
    "杭州拱宸桥美食",
    "杭州滨江夜跑",
    "杭州咖啡地图",
    "良渚文化村拍照",
    "杭州亲子游",
    "临安徒步路线",
    "富阳露营地",
    # 苏州
    "苏州路线",
    "苏州园林游玩攻略",
    "拙政园打卡",
    "平江路citywalk",
    "苏州博物馆参观指南",
    "阳澄湖大闸蟹季",
    "金鸡湖夜景",
    "周庄古镇一日游",
    "同里古镇漫游",
    "苏州拍照圣地",
    # 昆山
    "昆山路线",
    "昆山旅游路线",
    "昆山拍照圣地",
    "昆山亲子游",
    "千灯古镇游玩攻略",
    "周市美食清单",
    "花桥地铁出行攻略",
    "淀山湖露营地",
    "昆山夜生活",
    "昆山citywalk路线",
]

# 示例热榜标题
LOCAL_XHS_HOT_DOT_TITLES = [
    {
        "icon": "https://picasso-static.xiaohongshu.com/fe-platform/cfd317ff14757c7ede6ef5176ec487589565e49e.png",
        "id": "dora_1805424",
        "rank_change": 0,
        "score": "861.5万",
        "title": "陶渊明的审美还是太权威了",
        "title_img": "",
        "type": "normal",
        "word_type": "热"
    },
    {
        "icon": "https://picasso-static.xiaohongshu.com/fe-platform/be184ffb03399b2ea1d28a81f3991aac3224f9d3.png",
        "id": "dora_1806105",
        "rank_change": 35,
        "score": "716.5万",
        "title": "挑战干巴主理人",
        "title_img": "",
        "type": "normal",
        "word_type": "梗"
    },
    {
        "icon": "https://picasso-static.xiaohongshu.com/fe-platform/cfd317ff14757c7ede6ef5176ec487589565e49e.png",
        "id": "dora_1806121",
        "rank_change": 5,
        "score": "679.4万",
        "title": "落叶魔法帽 秋日拍照时尚单品",
        "title_img": "",
        "type": "normal",
        "word_type": "热"
    },
    {
        "id": "dora_1806750",
        "rank_change": 0,
        "score": "605.9万",
        "title": "梁靖崑全运会首战爆冷出局",
        "title_img": "",
        "type": "normal",
        "word_type": "无"
    },
    {
        "icon": "https://picasso-static.xiaohongshu.com/fe-platform/cfd317ff14757c7ede6ef5176ec487589565e49e.png",
        "id": "dora_1806304",
        "rank_change": 0,
        "score": "604.6万",
        "title": "我在现场看全运会",
        "title_img": "",
        "type": "normal",
        "word_type": "热"
    },
    {
        "icon": "https://sns-img-qc.xhscdn.com/search/trends/icon/label/new/version/1",
        "id": "dora_1806751",
        "rank_change": 0,
        "score": "599.7万",
        "title": "金鸡百花电影节开幕式",
        "title_img": "",
        "type": "normal",
        "word_type": "新"
    },
    {
        "id": "dora_1806268",
        "rank_change": -3,
        "score": "598.5万",
        "title": "德军司令称柏林已做好开战准备",
        "title_img": "",
        "type": "normal",
        "word_type": "无"
    },
    {
        "icon": "https://picasso-static.xiaohongshu.com/fe-platform/4d6304d79d71bd1f68611ae09184b778ec1a6d97.png",
        "id": "dora_1806542",
        "rank_change": 0,
        "score": "598.5万",
        "title": "水果姐来小红书求安利杭州攻略了",
        "title_img": "",
        "type": "normal",
        "word_type": "独家"
    },
    {
        "id": "dora_1805702",
        "rank_change": -6,
        "score": "597.4万",
        "title": "秋冬就做气质显白渲染美甲",
        "title_img": "",
        "type": "normal",
        "word_type": "无"
    },
    {
        "icon": "https://picasso-static.xiaohongshu.com/fe-platform/4d6304d79d71bd1f68611ae09184b778ec1a6d97.png",
        "id": "dora_1804909",
        "rank_change": -3,
        "score": "592.6万",
        "title": "莫言：小红书的朋友们好",
        "title_img": "",
        "type": "normal",
        "word_type": "独家"
    },
    {
        "id": "dora_1804634",
        "rank_change": 29,
        "score": "569.9万",
        "title": "独属于秋冬氛围的复古卷发",
        "title_img": "",
        "type": "normal",
        "word_type": "无"
    },
    {
        "icon": "https://picasso-static.xiaohongshu.com/fe-platform/cfd317ff14757c7ede6ef5176ec487589565e49e.png",
        "id": "dora_1806545",
        "rank_change": 0,
        "score": "569.5万",
        "title": "四位新闻女王其实是同一类人",
        "title_img": "",
        "type": "normal",
        "word_type": "热"
    },
    {
        "id": "dora_1805621",
        "rank_change": 1,
        "score": "565.9万",
        "title": "陈梦全运会首秀晋级女单16强",
        "title_img": "",
        "type": "normal",
        "word_type": "无"
    },
    {
        "id": "dora_1802432",
        "rank_change": -3,
        "score": "498万",
        "title": "冬天的第一口奶皮子蛋糕",
        "title_img": "",
        "type": "normal",
        "word_type": "无"
    },
    {
        "icon": "https://sns-img-qc.xhscdn.com/search/trends/icon/label/new/version/1",
        "id": "dora_1806765",
        "rank_change": 0,
        "score": "496.8万",
        "title": "唐朝诡事录有自己的大冰",
        "title_img": "",
        "type": "normal",
        "word_type": "新"
    },
    {
        "icon": "https://picasso-static.xiaohongshu.com/fe-platform/be184ffb03399b2ea1d28a81f3991aac3224f9d3.png",
        "id": "dora_1804027",
        "rank_change": 29,
        "score": "486.1万",
        "title": "动物界有自己的德华",
        "title_img": "",
        "type": "normal",
        "word_type": "梗"
    },
    {
        "id": "dora_1802828",
        "rank_change": 17,
        "score": "484.7万",
        "title": "用落叶贴出可爱的汉堡",
        "title_img": "",
        "type": "normal",
        "word_type": "无"
    },
    {
        "icon": "https://picasso-static.xiaohongshu.com/fe-platform/cfd317ff14757c7ede6ef5176ec487589565e49e.png",
        "id": "dora_1804077",
        "rank_change": -1,
        "score": "484.2万",
        "title": "唐诡3中薛环也能独当一面了",
        "title_img": "",
        "type": "normal",
        "word_type": "热"
    },
    {
        "id": "dora_1806156",
        "rank_change": -6,
        "score": "483.5万",
        "title": "又到了一碰小猫就噼里啪啦的季节",
        "title_img": "",
        "type": "normal",
        "word_type": "无"
    },
    {
        "id": "dora_1806513",
        "rank_change": -10,
        "score": "476.5万",
        "title": "全运会吉祥物背后的小演员找到了",
        "title_img": "",
        "type": "normal",
        "word_type": "无"
    }
]
