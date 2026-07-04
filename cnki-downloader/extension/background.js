// CNKI Cookie Injector + Auto Download Background Script
const CNKI_COOKIES = [{"name": "_c_WBKFRo", "value": "vx7kYIApPT34yebAB2MBy5vLlRPtOf0EKg8vA1ME"}, {"name": "Ecp_ClientIp", "value": "222.28.239.185"}, {"name": "cnkiUserKey", "value": "491cb460-3573-3ad7-a2d7-b2af30c2634f"}, {"name": "Ecp_loginuserbk", "value": "dx0741"}, {"name": "Ecp_loginuserjf", "value": "dx0741"}, {"name": "tfstk", "value": "goXmQTYprsRfGB0zKVJbg_27aQFRcK96ZNH9WdLaaU8SHtB9HlvGjUBv6ZCAZ1bdYE79HiHicTbnBxUbGGkMBdzLJJedcIp6QyIWdqUHlhsy7ud42AQcEdzLJ8CtHHa6QiLj519P4UtiQFkV7LlycUoquN82a4-HAd8N7N8rUHxB0x-w04lyPhJw7NJaqg8Wjd8N7drl4bu00EBNUTzOL0MnaMiownRD8i8oIi6k0Icf0UDZQTjvie7MrAkNEnjivMtiK5LFOEdp-ay-ndjyjaAdiyDcSGSC_QXiuoQF0Z6C_i2u8KBf06RNLPGN-KbMTtRobv9DUUJk49rtOUBkkNWDakHH6LWpTK58Nrd9nHbNhZmiQwSRvtO5Iy0y5sKBUhX_YfYM_g7naXzINAtzXTls1I-Wqee5fPQCCXG_yuqoTCO2VnTLqucsrI-W4eEuqXY6g3t2J"}, {"name": "sensorsdata2015jssdkcross", "value": "%7B%22distinct_id%22%3A%2219b62b3257879f-0e9ce6a55435a88-4c657b58-1474560-19b62b3257b864%22%2C%22first_id%22%3A%22%22%2C%22props%22%3A%7B%22%24latest_traffic_source_type%22%3A%22%E7%9B%B4%E6%8E%A5%E6%B5%81%E9%87%8F%22%2C%22%24latest_search_keyword%22%3A%22%E6%9C%AA%E5%8F%96%E5%88%B0%E5%80%BC_%E7%9B%B4%E6%8E%A5%E6%89%93%E5%BC%80%22%2C%22%24latest_referrer%22%3A%22%22%7D%2C%22%24device_id%22%3A%2219b62b3257879f-0e9ce6a55435a88-4c657b58-1474560-19b62b3257b864%22%7D"}, {"name": "Ecp_ClientId", "value": "e78899f8ed56aab5b3373cc6276273240VL9UT5N80"}, {"name": "SID", "value": "zhuye091002"}, {"name": "LID", "value": "WEEvREcwSlJHSldSdmVpZ0doelJ3VkMvejh6S1VLSkVvdUFieVZubEpKND0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!"}, {"name": "Ecp_session", "value": "1"}, {"name": "Ecp_notFirstLogin", "value": "J2o0nh"}, {"name": "Ecp_LoginStuts", "value": "{\"IsAutoLogin\":false,\"UserName\":\"dx0741\",\"ShowName\":\"%E4%B8%AD%E5%A4%AE%E6%B0%91%E6%97%8F%E5%A4%A7%E5%AD%A6%E5%9B%BE%E4%B9%A6%E9%A6%86\",\"UserType\":\"bk\",\"BUserName\":\"\",\"BShowName\":\"\",\"BUserType\":\"\",\"r\":\"J2o0nh\",\"Members\":[]}"}, {"name": "c_m_LinID", "value": "LinID=WEEvREcwSlJHSldSdmVpZ0doelJ3VkMvejh6S1VLSkVvdUFieVZubEpKND0=$9A4hF_YAuvQ5obgVAqNKPCYcEjKensW4IQMovwHtwkF4VYPoHbKxJw!!&ot=06%2F20%2F2026%2019%3A02%3A14"}, {"name": "c_m_expire", "value": "2026-06-20%2019%3A02%3A14"}];

const CNKI_DOMAINS = [
    '.cnki.net', 'www.cnki.net', 'kns.cnki.net', 'navi.cnki.net',
    'bar.cnki.net', 'login.cnki.net', 'rss.cnki.net', 'x.cnki.net',
    'gateway.cnki.net'
];

async function injectCookies() {
    let count = 0;
    for (const domain of CNKI_DOMAINS) {
        for (const cookie of CNKI_COOKIES) {
            try {
                const url = 'https://' + domain.replace(/^\./, '') + '/';
                await chrome.cookies.set({
                    url: url,
                    domain: domain,
                    name: cookie.name,
                    value: cookie.value,
                    path: '/',
                    secure: true,
                    sameSite: 'lax'
                });
                count++;
            } catch (e) {
                // Skip errors - cookie may exist or domain invalid
            }
        }
    }
    console.log('[CNKI AutoDL] Cookies injected: ' + count);
}

// Run on install, startup, and immediately
chrome.runtime.onInstalled.addListener(injectCookies);
chrome.runtime.onStartup.addListener(injectCookies);
injectCookies();
