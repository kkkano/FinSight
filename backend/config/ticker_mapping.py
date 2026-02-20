# -*- coding: utf-8 -*-
"""
Centralized Ticker Mapping and Extraction
Shared by IntentClassifier and ConversationRouter
"""

import re
from typing import Dict, List, Any

# Stock ticker to company name mapping
COMPANY_MAP: Dict[str, str] = {
    # US Tech
    'AAPL': 'Apple', 'apple': 'AAPL',
    'GOOGL': 'Google', 'google': 'GOOGL', 'alphabet': 'GOOGL',
    'GOOG': 'Google',
    'MSFT': 'Microsoft', 'microsoft': 'MSFT',
    'AMZN': 'Amazon', 'amazon': 'AMZN',
    'META': 'Meta', 'facebook': 'META',
    'TSLA': 'Tesla', 'tesla': 'TSLA',
    'NVDA': 'NVIDIA', 'nvidia': 'NVDA',
    'AMD': 'AMD',
    'INTC': 'Intel', 'intel': 'INTC',
    'NFLX': 'Netflix', 'netflix': 'NFLX',
    'CRM': 'Salesforce', 'salesforce': 'CRM',
    # Chinese ADRs
    'BABA': 'Alibaba', 'alibaba': 'BABA',
    'JD': 'JD.com', 'jd': 'JD',
    'PDD': 'Pinduoduo', 'pinduoduo': 'PDD',
    'BIDU': 'Baidu', 'baidu': 'BIDU',
    'NIO': 'NIO', 'nio': 'NIO',
    'XPEV': 'XPeng', 'xpeng': 'XPEV',
    'LI': 'Li Auto', 'li auto': 'LI',
    # ETFs
    'SPY': 'S&P 500 ETF',
    'QQQ': 'Nasdaq 100 ETF',
    'DIA': 'Dow Jones ETF',
    'IWM': 'Russell 2000 ETF',
    'VTI': 'Total Stock Market ETF',
}

# Chinese name to ticker mapping
CN_TO_TICKER: Dict[str, str] = {
    '苹果': 'AAPL', '谷歌': 'GOOGL', '微软': 'MSFT',
    '亚马逊': 'AMZN', '特斯拉': 'TSLA', '英伟达': 'NVDA',
    '阿里巴巴': 'BABA', '阿里': 'BABA', '京东': 'JD',
    '拼多多': 'PDD', '百度': 'BIDU', '英特尔': 'INTC',
    '蔚来': 'NIO', '小鹏': 'XPEV', '理想': 'LI',
    '凯捷': 'CAP.PA', '奈飞': 'NFLX', '脸书': 'META',
    # Market indices
    '纳斯达克': '^IXIC', '纳斯达克指数': '^IXIC', '纳指': '^IXIC',
    '道琼斯': '^DJI', '道琼斯指数': '^DJI', '道指': '^DJI',
    '标普500': '^GSPC', '标普': '^GSPC', 'S&P 500': '^GSPC', 'sp500': '^GSPC',
    '罗素2000': '^RUT', 'VIX': '^VIX', '恐慌指数': '^VIX',
    '纽交所': '^NYA', '纽交所指数': '^NYA',
    '富时100': '^FTSE', '日经225': '^N225', '恒生指数': '^HSI',
    # Commodities
    '黄金': 'GC=F', '金价': 'GC=F', 'gold': 'GC=F',
    '白银': 'SI=F', '银价': 'SI=F', 'silver': 'SI=F',
    '原油': 'CL=F', '油价': 'CL=F', 'crude oil': 'CL=F', 'oil': 'CL=F',
    # A-shares indices
    '沪深300': '000300.SS', '沪深三百': '000300.SS', 'csi300': '000300.SS',
    '上证指数': '000001.SS', '上证': '000001.SS', '上证综指': '000001.SS',
    '深证成指': '399001.SZ', '深证': '399001.SZ',
    '创业板': '399006.SZ', '创业板指': '399006.SZ',
}

# Market index aliases
INDEX_ALIASES: Dict[str, str] = {
    # Nasdaq
    '纳斯达克': '^IXIC', '纳斯达克指数': '^IXIC', '纳指': '^IXIC',
    'nasdaq': '^IXIC', 'nasdaq composite': '^IXIC',
    # Dow Jones
    '道琼斯': '^DJI', '道琼斯指数': '^DJI', '道指': '^DJI',
    'dow jones': '^DJI', 'dow': '^DJI',
    # S&P 500
    '标普500': '^GSPC', '标普': '^GSPC', 'S&P 500': '^GSPC',
    'sp500': '^GSPC', 'sp 500': '^GSPC', '标准普尔500': '^GSPC',
    # Others
    '罗素2000': '^RUT', 'russell 2000': '^RUT',
    'VIX': '^VIX', '恐慌指数': '^VIX', 'vix指数': '^VIX',
    '纽交所': '^NYA', '纽交所指数': '^NYA', 'nyse': '^NYA',
}

# Known valid tickers (skip common word filtering)
KNOWN_TICKERS = {
    'AAPL', 'GOOGL', 'GOOG', 'MSFT', 'AMZN', 'META', 'TSLA', 'NVDA', 'AMD', 'INTC',
    'NFLX', 'CRM', 'BABA', 'JD', 'PDD', 'BIDU', 'NIO', 'XPEV', 'LI',
    'SPY', 'QQQ', 'DIA', 'IWM', 'VTI'
}

# Common words to filter out (not tickers)
COMMON_WORDS = {
    # Single/two-letter
    'A', 'I', 'AM', 'PM', 'US', 'UK', 'AI', 'UP', 'DOWN', 'IN', 'ON', 'AT',
    'IS', 'IT', 'OF', 'TO', 'AS', 'BE', 'BY', 'DO', 'GO', 'IF', 'ME', 'MY',
    'NO', 'OR', 'SO', 'WE', 'AN', 'HE',
    # Finance abbreviations (not ticker symbols)
    'CEO', 'IPO', 'ETF', 'VS', 'PE', 'EPS', 'MACD', 'RSI', 'KDJ', 'ROI',
    'ROE', 'ROA', 'GDP', 'CPI', 'PPI', 'EBIT', 'SEC', 'FED', 'FOMC', 'YTD',
    'QOQ', 'YOY', 'NAV', 'AUM', 'OTC', 'ATH', 'ATL', 'APR', 'APY', 'CAGR',
    # Common English words (3+ letters)
    'THE', 'AND', 'FOR', 'ARE', 'BUT', 'NOT', 'YOU', 'ALL', 'CAN', 'HAD',
    'HER', 'WAS', 'ONE', 'OUR', 'OUT', 'HAS', 'HIS', 'HOW', 'ITS', 'MAY',
    'NEW', 'NOW', 'OLD', 'SEE', 'WAY', 'WHO', 'BOY', 'DID', 'GET', 'HIM',
    'LET', 'PUT', 'SAY', 'SHE', 'TOO', 'USE', 'DAY', 'BIG', 'RUN', 'GOT',
    'SET', 'TOP', 'TRY', 'END', 'FAR', 'OWN', 'ASK', 'MEN', 'ODD', 'ADD',
    'AGE', 'AGO', 'AID', 'AIM', 'AIR', 'ARM', 'ART', 'BAD', 'BAR', 'BED',
    'BIT', 'BOX', 'BUS', 'CUT', 'DIE', 'DOG', 'DRY', 'DUE', 'EAR', 'EAT',
    'ERA', 'EYE', 'FAN', 'FAT', 'FEW', 'FIT', 'FLY', 'FOR', 'GAS', 'GUN',
    'GUY', 'HAT', 'HIT', 'HOT', 'ICE', 'ILL', 'JOB', 'JOY', 'KEY', 'KID',
    'LAW', 'LAY', 'LED', 'LEG', 'LIE', 'LOT', 'LOW', 'MAP', 'MIX', 'MOM',
    'MUD', 'NET', 'NOR', 'NUT', 'OIL', 'PAY', 'PAN', 'PEN', 'PER', 'PIE',
    'PIN', 'PIT', 'RAW', 'RED', 'RID', 'ROW', 'SAD', 'SAT', 'SEA', 'SIT',
    'SIX', 'SKI', 'SKY', 'SON', 'SUM', 'SUN', 'TAX', 'TEN', 'THE', 'TIE',
    'TIP', 'TON', 'TWO', 'VAN', 'WAR', 'WEB', 'WET', 'WIN', 'WON', 'YET',
    'YES', 'ZIP',
    # 4-letter common English words — the primary source of false positives
    'ABLE', 'ALSO', 'AREA', 'ARMY', 'AWAY', 'BABY', 'BACK', 'BALL', 'BAND',
    'BANK', 'BASE', 'BATH', 'BEAN', 'BEAT', 'BEEN', 'BEST', 'BILL', 'BIRD',
    'BLOW', 'BLUE', 'BOAT', 'BODY', 'BOMB', 'BONE', 'BOOK', 'BORN', 'BOSS',
    'BOTH', 'BURN', 'BUSY', 'CAKE', 'CAME', 'CAMP', 'CARD', 'CARE', 'CASE',
    'CAST', 'CELL', 'CHAT', 'CHIP', 'CITY', 'CLUB', 'COAT', 'CODE', 'COLD',
    'COME', 'COOK', 'COOL', 'COPY', 'CORE', 'CREW', 'CROP', 'DARK', 'DATE',
    'DEAD', 'DEAL', 'DEAR', 'DEEP', 'DENY', 'DESK', 'DIAL', 'DIRT', 'DISH',
    'DOCK', 'DOES', 'DONE', 'DOOR', 'DOSE', 'DOWN', 'DRAG', 'DRAW', 'DREW',
    'DROP', 'DRUG', 'DRUM', 'DUAL', 'DULL', 'DUMP', 'DUST', 'DUTY', 'EACH',
    'EARN', 'EASE', 'EAST', 'EASY', 'EDGE', 'EDIT', 'ELSE', 'EVEN', 'EVER',
    'EVIL', 'EXAM', 'EXEC', 'EXIT', 'FACE', 'FACT', 'FAIL', 'FAIR', 'FALL',
    'FAME', 'FARM', 'FAST', 'FATE', 'FEAR', 'FEED', 'FEEL', 'FEET', 'FELL',
    'FILE', 'FILL', 'FILM', 'FIND', 'FINE', 'FIRE', 'FIRM', 'FISH', 'FLAG',
    'FLAT', 'FLED', 'FLEW', 'FLIP', 'FLOW', 'FOLD', 'FOLK', 'FOOD', 'FOOL',
    'FOOT', 'FORM', 'FORT', 'FOUL', 'FOUR', 'FREE', 'FROM', 'FUEL', 'FULL',
    'GAIN', 'GAME', 'GANG', 'GATE', 'GAVE', 'GEAR', 'GENE', 'GIFT', 'GIRL',
    'GLAD', 'GOES', 'GOLD', 'GOLF', 'GONE', 'GOOD', 'GRAB', 'GRAY', 'GREW',
    'GREY', 'GRIP', 'GROW', 'GULF', 'GURU', 'GUYS', 'HALF', 'HALL', 'HAND',
    'HANG', 'HARD', 'HARM', 'HATE', 'HAVE', 'HEAD', 'HEAL', 'HEAR', 'HEAT',
    'HELD', 'HERE', 'HERO', 'HIDE', 'HINT', 'HIRE', 'HITS', 'HOLE', 'HOME',
    'HOPE', 'HOST', 'HOUR', 'HUGE', 'HUNG', 'HUNT', 'HURT', 'ICON', 'IDEA',
    'INTO', 'IRON', 'ITEM', 'JACK', 'JAIL', 'JANE', 'JEAN', 'JOBS', 'JOIN',
    'JOKE', 'JUMP', 'JURY', 'JUST', 'KEEN', 'KEEP', 'KEPT', 'KICK', 'KILL',
    'KIND', 'KING', 'KNEE', 'KNEW', 'KNOT', 'KNOW', 'LACK', 'LADY', 'LAID',
    'LAKE', 'LAND', 'LANE', 'LAST', 'LATE', 'LEAD', 'LEAN', 'LEFT', 'LEND',
    'LESS', 'LIES', 'LIFE', 'LIFT', 'LIKE', 'LINE', 'LINK', 'LIST', 'LIVE',
    'LOAD', 'LOCK', 'LOGO', 'LONE', 'LOOK', 'LORD', 'LOSE', 'LOSS', 'LOST',
    'LOTS', 'LOVE', 'LUCK', 'LUNG', 'MADE', 'MAIL', 'MAIN', 'MAKE', 'MALE',
    'MAMA', 'MANY', 'MARK', 'MASS', 'MATE', 'MATH', 'MEAL', 'MEAN', 'MEAT',
    'MEET', 'MENU', 'MERE', 'MESS', 'MILD', 'MILE', 'MILK', 'MIND', 'MINE',
    'MISS', 'MODE', 'MOOD', 'MOON', 'MORE', 'MOST', 'MOVE', 'MUCH', 'MUST',
    'MYTH', 'NAIL', 'NAME', 'NEAR', 'NEAT', 'NECK', 'NEED', 'NEXT', 'NICE',
    'NINE', 'NODE', 'NONE', 'NOSE', 'NOTE', 'NOUN', 'ODDS', 'OKAY', 'ONCE',
    'ONLY', 'ONTO', 'OPEN', 'ORAL', 'OURS', 'OVER', 'PACE', 'PACK', 'PAGE',
    'PAID', 'PAIN', 'PAIR', 'PALE', 'PALM', 'PAPA', 'PARK', 'PART', 'PASS',
    'PAST', 'PATH', 'PEAK', 'PEER', 'PICK', 'PILE', 'PINE', 'PINK', 'PIPE',
    'PLAN', 'PLAY', 'PLOT', 'PLUG', 'PLUS', 'POEM', 'POET', 'POLL', 'POND',
    'POOL', 'POOR', 'POPE', 'PORK', 'PORT', 'POSE', 'POST', 'POUR', 'PRAY',
    'PULL', 'PUMP', 'PURE', 'PUSH', 'QUIT', 'RACE', 'RAIN', 'RANK', 'RAPE',
    'RARE', 'READ', 'REAL', 'REAR', 'RELY', 'RENT', 'REST', 'RICE', 'RICH',
    'RIDE', 'RING', 'RISE', 'ROAD', 'ROCK', 'RODE', 'ROLE', 'ROLL', 'ROOF',
    'ROOM', 'ROOT', 'ROPE', 'ROSE', 'RULE', 'RUSH', 'RUTH', 'SAFE', 'SAID',
    'SAKE', 'SALE', 'SALT', 'SAME', 'SAND', 'SANG', 'SAVE', 'SEAL', 'SEAT',
    'SEED', 'SEEK', 'SEEM', 'SEEN', 'SELF', 'SELL', 'SEND', 'SENT', 'SEPT',
    'SHIP', 'SHOP', 'SHOT', 'SHOW', 'SHUT', 'SICK', 'SIDE', 'SIGN', 'SILK',
    'SINK', 'SITE', 'SIZE', 'SKIN', 'SLIM', 'SLIP', 'SLOT', 'SLOW', 'SNAP',
    'SNOW', 'SOAR', 'SOFT', 'SOIL', 'SOLD', 'SOLE', 'SOME', 'SONG', 'SOON',
    'SORT', 'SOUL', 'SPAN', 'SPIN', 'SPOT', 'STAR', 'STAY', 'STEM', 'STEP',
    'STIR', 'STOP', 'SUCH', 'SUIT', 'SURE', 'SWIM', 'TAIL', 'TAKE', 'TALE',
    'TALK', 'TALL', 'TANK', 'TAPE', 'TASK', 'TEAM', 'TEAR', 'TECH', 'TEEN',
    'TELL', 'TEND', 'TENT', 'TERM', 'TEST', 'TEXT', 'THAN', 'THAT', 'THEM',
    'THEN', 'THEY', 'THIN', 'THIS', 'THUS', 'TIDE', 'TIED', 'TIER', 'TILL',
    'TIME', 'TINY', 'TIRE', 'TOAD', 'TOLD', 'TOLL', 'TOMB', 'TONE', 'TOOK',
    'TOOL', 'TOPS', 'TORE', 'TORN', 'TOUR', 'TOWN', 'TRAP', 'TREE', 'TRIM',
    'TRIO', 'TRIP', 'TRUE', 'TUBE', 'TUCK', 'TUNE', 'TURN', 'TWIN', 'TYPE',
    'UGLY', 'UNDO', 'UNIT', 'UPON', 'URGE', 'USED', 'USER', 'VAIN', 'VARY',
    'VAST', 'VERB', 'VERY', 'VICE', 'VIEW', 'VINE', 'VISA', 'VOID', 'VOLT',
    'VOTE', 'WADE', 'WAGE', 'WAIT', 'WAKE', 'WALK', 'WALL', 'WANT', 'WARD',
    'WARM', 'WARN', 'WASH', 'WAVE', 'WEAK', 'WEAR', 'WEED', 'WELL', 'WENT',
    'WERE', 'WEST', 'WHAT', 'WHEN', 'WHOM', 'WIDE', 'WIFE', 'WILD', 'WILL',
    'WIND', 'WINE', 'WING', 'WIRE', 'WISE', 'WISH', 'WITH', 'WOOD', 'WOOL',
    'WORD', 'WORE', 'WORK', 'WORM', 'WORN', 'WRAP', 'YARD', 'YEAH', 'ZERO',
    'ZONE',
    # 5-letter common words
    'ABOUT', 'ABOVE', 'ADDED', 'AFTER', 'AGAIN', 'AGREE', 'AHEAD', 'AIMED',
    'ALARM', 'ALLOW', 'ALONE', 'ALONG', 'AMONG', 'ANGLE', 'ANGRY', 'APART',
    'APPLY', 'ARISE', 'ASIDE', 'AUDIO', 'AVOID', 'AWARD', 'AWARE', 'BASED',
    'BASIC', 'BASIS', 'BEGIN', 'BEING', 'BELOW', 'BIRTH', 'BLACK', 'BLADE',
    'BLAME', 'BLANK', 'BLAST', 'BLAZE', 'BLEED', 'BLEND', 'BLIND', 'BLOCK',
    'BLOOD', 'BLOWN', 'BOARD', 'BONUS', 'BOOST', 'BOUND', 'BRAIN', 'BRAND',
    'BRAVE', 'BREAD', 'BREAK', 'BRIEF', 'BRING', 'BROAD', 'BROKE', 'BROWN',
    'BUILD', 'BUILT', 'BURST', 'BUYER', 'CARRY', 'CATCH', 'CAUSE', 'CHAIN',
    'CHAIR', 'CHEAP', 'CHECK', 'CHIEF', 'CHILD', 'CHINA', 'CHOSE', 'CIVIL',
    'CLAIM', 'CLASS', 'CLEAN', 'CLEAR', 'CLIMB', 'CLOCK', 'CLOSE', 'CLOTH',
    'CLOUD', 'COACH', 'COAST', 'COLOR', 'COUCH', 'COULD', 'COUNT', 'COURT',
    'COVER', 'CRACK', 'CRAFT', 'CRASH', 'CRAZY', 'CREAM', 'CRIME', 'CROSS',
    'CROWD', 'CROWN', 'CRUDE', 'CURVE', 'CYCLE', 'DAILY', 'DANCE', 'DEATH',
    'DEBUT', 'DELAY', 'DEPTH', 'DIRTY', 'DOUBT', 'DOZEN', 'DRAFT', 'DRAIN',
    'DRAMA', 'DRANK', 'DRAWN', 'DREAM', 'DRESS', 'DRIED', 'DRINK', 'DRIVE',
    'DROVE', 'DYING', 'EAGER', 'EARLY', 'EARTH', 'EIGHT', 'ELECT', 'ELITE',
    'EMPTY', 'ENEMY', 'ENJOY', 'ENTER', 'ENTRY', 'EQUAL', 'ERROR', 'EVENT',
    'EVERY', 'EXACT', 'EXIST', 'EXTRA', 'FAITH', 'FALSE', 'FANCY', 'FATAL',
    'FAULT', 'FAVOR', 'FENCE', 'FEWER', 'FIBER', 'FIELD', 'FIFTH', 'FIFTY',
    'FIGHT', 'FINAL', 'FIRST', 'FIXED', 'FLAME', 'FLASH', 'FLESH', 'FLOAT',
    'FLOOD', 'FLOOR', 'FLOUR', 'FOCUS', 'FORCE', 'FORTH', 'FOUND', 'FRAME',
    'FRANK', 'FRAUD', 'FRESH', 'FRONT', 'FRUIT', 'FUNNY', 'GIVEN', 'GLASS',
    'GLOBE', 'GONNA', 'GRACE', 'GRADE', 'GRAIN', 'GRAND', 'GRANT', 'GRASS',
    'GRAVE', 'GREAT', 'GREEN', 'GROSS', 'GROUP', 'GROWN', 'GUARD', 'GUESS',
    'GUEST', 'GUIDE', 'GUILT', 'HAPPY', 'HARSH', 'HEARD', 'HEART', 'HEAVY',
    'HENCE', 'HORSE', 'HOTEL', 'HOUSE', 'HUMAN', 'HUMOR', 'HURRY', 'IDEAL',
    'IMAGE', 'IMPLY', 'INDEX', 'INDIA', 'INNER', 'INPUT', 'ISSUE', 'IVORY',
    'JAPAN', 'JOINT', 'JUDGE', 'JUICE', 'KNIFE', 'KNOCK', 'KNOWN', 'LABEL',
    'LABOR', 'LARGE', 'LATER', 'LAUGH', 'LAYER', 'LEARN', 'LEASE', 'LEAST',
    'LEAVE', 'LEGAL', 'LEVEL', 'LIGHT', 'LIMIT', 'LITER', 'LIVES', 'LOCAL',
    'LOGIC', 'LOOSE', 'LOVER', 'LOWER', 'LUCKY', 'LUNCH', 'LYING', 'MAGIC',
    'MAJOR', 'MAKER', 'MARCH', 'MATCH', 'MAYOR', 'MAYBE', 'MEDIA', 'MERGE',
    'MERIT', 'METAL', 'METER', 'MICRO', 'MIGHT', 'MINOR', 'MINUS', 'MIXED',
    'MODEL', 'MONEY', 'MONTH', 'MORAL', 'MOUNT', 'MOUSE', 'MOUTH', 'MOVED',
    'MOVIE', 'MUSIC', 'NAMED', 'NERVE', 'NEVER', 'NEWLY', 'NIGHT', 'NINTH',
    'NOISE', 'NORTH', 'NOTED', 'NOVEL', 'NURSE', 'OCCUR', 'OCEAN', 'OFFER',
    'OFTEN', 'ONSET', 'OPERA', 'ORBIT', 'OTHER', 'OUGHT', 'OUTER', 'OWNED',
    'OWNER', 'OXIDE', 'PAINT', 'PANEL', 'PANIC', 'PAPER', 'PARTY', 'PATCH',
    'PAUSE', 'PEACE', 'PENNY', 'PHASE', 'PHONE', 'PHOTO', 'PIANO', 'PIECE',
    'PILOT', 'PITCH', 'PIXEL', 'PLACE', 'PLAIN', 'PLANE', 'PLANT', 'PLATE',
    'PLAZA', 'PLEAD', 'PLUMB', 'POINT', 'POUND', 'POWER', 'PRESS', 'PRIDE',
    'PRIME', 'PRINT', 'PRIOR', 'PRIZE', 'PROOF', 'PROUD', 'PROVE', 'PULSE',
    'PUNCH', 'PUPIL', 'QUEEN', 'QUEST', 'QUEUE', 'QUICK', 'QUIET', 'QUITE',
    'QUOTA', 'QUOTE', 'RADAR', 'RADIO', 'RAISE', 'RALLY', 'RANGE', 'RAPID',
    'RATIO', 'REACH', 'REACT', 'READY', 'REALM', 'REBEL', 'REFER', 'REIGN',
    'RELAX', 'REPLY', 'RIDER', 'RIGHT', 'RIGID', 'RISKY', 'RIVAL', 'RIVER',
    'ROBOT', 'ROGER', 'ROMAN', 'ROUGH', 'ROUND', 'ROUTE', 'ROYAL', 'RULED',
    'RULER', 'RURAL', 'SADLY', 'SAINT', 'SCALE', 'SCENE', 'SCOPE', 'SCORE',
    'SENSE', 'SERVE', 'SETUP', 'SEVEN', 'SHALL', 'SHAME', 'SHAPE', 'SHARP',
    'SHEET', 'SHELF', 'SHELL', 'SHIFT', 'SHINE', 'SHIRT', 'SHOCK', 'SHOOT',
    'SHORT', 'SHOUT', 'SIGHT', 'SINCE', 'SIXTH', 'SIXTY', 'SIZED', 'SKILL',
    'SLEEP', 'SLICE', 'SLIDE', 'SMALL', 'SMART', 'SMELL', 'SMILE', 'SMOKE',
    'SOLID', 'SOLVE', 'SORRY', 'SOUND', 'SOUTH', 'SPACE', 'SPARE', 'SPEAK',
    'SPEED', 'SPEND', 'SPENT', 'SPLIT', 'SPOKE', 'SPRAY', 'STACK', 'STAFF',
    'STAGE', 'STAIN', 'STAKE', 'STALE', 'STALL', 'STAMP', 'STAND', 'STARK',
    'START', 'STATE', 'STEAL', 'STEAM', 'STEEL', 'STEEP', 'STEER', 'STERN',
    'STICK', 'STIFF', 'STILL', 'STONE', 'STOOD', 'STORE', 'STORM', 'STORY',
    'STRIP', 'STUCK', 'STUDY', 'STUFF', 'STYLE', 'SUGAR', 'SUITE', 'SUPER',
    'SURGE', 'SWEAR', 'SWEEP', 'SWEET', 'SWEPT', 'SWING', 'TABLE', 'TAKEN',
    'TASTE', 'TEACH', 'TEETH', 'TEMPO', 'THANK', 'THEME', 'THERE', 'THICK',
    'THING', 'THINK', 'THIRD', 'THREE', 'THREW', 'THROW', 'THUMB', 'TIGHT',
    'TIRED', 'TITLE', 'TODAY', 'TOKEN', 'TOPIC', 'TOTAL', 'TOUCH', 'TOUGH',
    'TOWER', 'TOXIC', 'TRACE', 'TRACK', 'TRAIL', 'TRAIN', 'TRAIT', 'TREAT',
    'TREND', 'TRIAL', 'TRIBE', 'TRICK', 'TRIED', 'TROOP', 'TRUCK', 'TRULY',
    'TRUMP', 'TRUNK', 'TRUST', 'TRUTH', 'TUMOR', 'TWICE', 'TWIST', 'ULTRA',
    'UNCLE', 'UNDER', 'UNION', 'UNITE', 'UNITY', 'UNTIL', 'UPPER', 'UPSET',
    'URBAN', 'USAGE', 'USUAL', 'UTTER', 'VALID', 'VALUE', 'VIDEO', 'VIGOR',
    'VIRAL', 'VIRUS', 'VISIT', 'VITAL', 'VIVID', 'VOCAL', 'VOICE', 'VOTER',
    'WASTE', 'WATCH', 'WATER', 'WEIGH', 'WEIRD', 'WHEEL', 'WHERE', 'WHICH',
    'WHILE', 'WHITE', 'WHOLE', 'WHOSE', 'WIDER', 'WOMAN', 'WOMEN', 'WORLD',
    'WORRY', 'WORSE', 'WORST', 'WORTH', 'WOULD', 'WOUND', 'WRITE', 'WRONG',
    'WROTE', 'YIELD', 'YOUNG', 'YOUTH',
    # Finance/trading terms that look like tickers but aren't
    'HIGH', 'LOW', 'BUY', 'SELL', 'HOLD', 'LONG', 'SHORT', 'CALL', 'BULL',
    'BEAR', 'RISK', 'GAIN', 'LOSS', 'CASH', 'BOND', 'FUND', 'LOAN', 'DEBT',
    'RATE', 'TERM', 'YEAR', 'WEEK', 'MONTH', 'PRICE', 'VALUE', 'COST',
    'NEWS', 'INFO', 'DATA', 'CHART', 'TREND', 'STOCK', 'SHARE', 'TRADE',
    'ORDER', 'LIMIT', 'STOP', 'WHAT', 'WHEN', 'WHERE', 'WHY', 'WHICH',
    'ABOUT', 'SHOW', 'TELL', 'GIVE', 'FIND', 'LOOK', 'HELP', 'GOLD', 'OIL',
}


def is_probably_ticker(ticker: str) -> bool:
    if not ticker:
        return False
    if _is_structured_market_ticker(ticker):
        return True
    if ticker in COMMON_WORDS:
        return False
    if ticker.startswith("^"):
        return True
    if len(ticker) > 12:
        return False
    return bool(re.match(r"^[A-Z0-9]{1,6}([.-][A-Z0-9]{1,4})?$", ticker))


def _is_structured_market_ticker(ticker: str) -> bool:
    text = str(ticker or "").strip().upper()
    return bool(re.match(r"^\d{5,6}\.(SS|SZ|BJ|HK)$", text))


def normalize_ticker(raw: str) -> str:
    """
    将任意用户输入（公司名 / 别名 / ticker）规范化为标准 ticker。

    优先级：CN_TO_TICKER → COMPANY_MAP（小写别名 → ticker）→ 原样返回大写。
    """
    stripped = raw.strip()
    if not stripped:
        return stripped

    # 中文名 → ticker
    if stripped in CN_TO_TICKER:
        return CN_TO_TICKER[stripped]

    lower = stripped.lower()
    mapped = COMPANY_MAP.get(lower)
    # COMPANY_MAP 中 value 为大写 ticker 的项是「别名 → ticker」映射
    if mapped and mapped == mapped.upper() and len(mapped) <= 6:
        return mapped

    return stripped.upper()


def dedup_tickers(tickers: List[str]) -> List[str]:
    """
    对 ticker 列表做规范化 + 去重（保留首次出现顺序）。
    """
    seen: set[str] = set()
    result: List[str] = []
    for t in tickers:
        canonical = normalize_ticker(t)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def extract_tickers(query: str) -> Dict[str, Any]:
    """
    Extract tickers and company names from query

    Returns:
        Dict with keys: tickers, company_names, company_mentions, is_comparison
    """
    metadata = {
        'tickers': [],
        'company_names': [],
        'company_mentions': [],
        'is_comparison': False
    }

    query_lower = query.lower()
    query_original = query

    # Check for comparison query
    comparison_keywords = ['对比', '比较', 'vs', 'versus', '区别', '差异', 'compare']
    if any(kw in query_lower for kw in comparison_keywords):
        metadata['is_comparison'] = True

    # 1. Match market indices (longest match first)
    sorted_aliases = sorted(INDEX_ALIASES.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        pattern = re.compile(re.escape(alias), re.IGNORECASE)
        if pattern.search(query_original):
            ticker = INDEX_ALIASES[alias]
            if ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)
                metadata['company_names'].append(alias)

    # 2. Match English tickers
    # Keep original case to distinguish user-typed TICKER from ordinary words
    raw_matches = re.findall(r'(?<![A-Za-z0-9.])([A-Za-z]{2,5})(?![A-Za-z0-9])', query)
    originally_upper = {m for m in raw_matches if m == m.upper() and len(m) >= 2}
    index_tickers = re.findall(r'(\^[A-Za-z]{3,})', query)
    raw_matches.extend(index_tickers)
    dotted_tickers = re.findall(r'(?<![A-Za-z])([A-Za-z]{1,5}[.-][A-Za-z]{1,4})(?![A-Za-z])', query)
    raw_matches.extend(dotted_tickers)
    cn_dotted_tickers = re.findall(r'(?<![A-Za-z0-9])(\d{5,6}\.(?:SS|SZ|BJ|HK))(?![A-Za-z0-9])', query, flags=re.IGNORECASE)
    raw_matches.extend(cn_dotted_tickers)
    potential_tickers = [t.upper() for t in raw_matches]

    for ticker in potential_tickers:
        if not is_probably_ticker(ticker):
            continue
        if ticker in KNOWN_TICKERS or ticker.startswith('^'):
            if ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)
        elif ticker.lower() in COMPANY_MAP:
            real_ticker = COMPANY_MAP.get(ticker.lower())
            if real_ticker and real_ticker not in metadata['tickers']:
                metadata['tickers'].append(real_ticker)
        else:
            # Only accept unknown tickers if they appeared in ALL CAPS in
            # the original query — this filters out ordinary English words
            # (e.g. "with", "view") while preserving user-typed symbols
            # (e.g. "PLTR", "SOFI").
            if (ticker in originally_upper or _is_structured_market_ticker(ticker)) and ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)

    # 3. Match Chinese company names
    sorted_cn_names = sorted(CN_TO_TICKER.keys(), key=len, reverse=True)
    for cn_name in sorted_cn_names:
        if cn_name in query_original:
            ticker = CN_TO_TICKER[cn_name]
            if ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)
                metadata['company_names'].append(cn_name)

    # 4. Match English company names (full names)
    for name, ticker in COMPANY_MAP.items():
        if len(name) > 4 and name.lower() in query_lower:
            if ticker not in metadata['tickers']:
                metadata['tickers'].append(ticker)
                metadata['company_names'].append(name)

    # 最后统一规范化 + 去重，防止别名与标准 ticker 共存
    metadata['tickers'] = dedup_tickers(metadata['tickers'])

    return metadata
