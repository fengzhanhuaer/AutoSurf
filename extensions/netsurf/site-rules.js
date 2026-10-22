(function (root) {
  const rules = {
    "haidan.cc": {modalAttendance: true, homePaths: ["/"], detailFillOnly: true, profileMetrics: {bonus: "#magic_num"}},
    "haidan.video": {modalAttendance: true, homePaths: ["/"], detailFillOnly: true, profileMetrics: {bonus: "#magic_num"}},
    "htpt.cc": {
      reuseRecentPage: true, homePaths: ["/"], refreshInNewPage: true, navigationRetries: 2,
      continueAttendanceForm: true,
      preferAttendanceSubmit: true,
      attendanceLabel: /^立即签到[（(]第\s*\d+\s*天[，,]\s*可获得\s*[\d,.]+\s*魔力值[）)]$/
    },
    "jpopsuki.eu": {
      accountPath: "/user.php",
      profileSelector: "#userinfo_stats",
      levelListSelector: "ul.stats > li",
      reuseRecentPage: true,
      navigationRetries: 2,
      profilePatterns: {
        uploaded: /\bUp\s*:\s*([\d,.]+\s*(?:[KMGTPE]i?B|B))/i,
        downloaded: /\bDown\s*:\s*([\d,.]+\s*(?:[KMGTPE]i?B|B))/i
      }
    },
    "hdsky.me": {
      imageCaptcha: "hdsky",
      reuseRecentPage: true,
      navigationRetries: 2,
      manualMessage: "HDSky 图片验证码未能可靠识别，请在网页中处理"
    },
    "gamegamept.com": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得G值\s*[\]】]?$/
    },
    "agsvpt.com": {
      homePaths: ["/"],
      duplicateAttendanceLinks: true,
      preferAttendanceSubmit: true,
      reuseRecentPage: true,
      navigationRetries: 2,
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得冰晶\s*[\]】]?$/,
      profilePatterns: {bonus: /冰晶\s*(?:\[使用\])?\s*[:：]?\s*([\d,.]+)/},
      profileLabels: {bonus: /^冰晶$/}
    },
    "monikadesign.uk": {
      refreshInNewPage: true,
      reuseRecentPage: true,
      navigationRetries: 2,
      profileMetrics: {
        uploaded: '.top-nav__stats-up',
        downloaded: '.top-nav__stats-down',
        ratio: '.top-nav__stats-ratio',
        bonus: '[class*="top-nav"] [title="魔力"]'
      }
    },
    "nanyangpt.com": {
      refreshInNewPage: true,
      reuseRecentPage: true,
      navigationRetries: 2,
      profileRow: /用户组\s*[:：]/,
      profilePatterns: {bonus: /魔力豆\s*[（(]\s*([\d,.]+)/},
      profileMetrics: {bonus: 'a[href="mybonus.php"], a[href="/mybonus.php"]'}
    },
    "piggo.me": {
      homePaths: ["/"],
      waitForSecurityChallenge: true,
      nativeAttendanceNavigation: true,
      reuseRecentPage: true,
      navigationRetries: 2,
      profileRow: /^\s*欢迎回来/,
      attendanceDoneText: /\[\s*签到已得\s*[\d,.]+\s*(?:[,，]\s*补签卡\s*[:：]\s*\d+)?\s*\]/
    },
    "pt.0ff.cc": {
      homePaths: ["/"],
      reuseRecentPage: true,
      navigationRetries: 2,
      continueAttendanceForm: true,
      sliderCaptcha: "freefarm",
      manualMessage: "Free Farm 滑块验证未通过，请在网页中处理"
    },
    "ourbits.club": {
      reuseRecentPage: true,
      navigationRetries: 2,
      profileRow: /^\s*欢迎回来/,
      attendanceDoneText: /[（(]\s*签到已得\s*[\d,.]+\s*[）)]/
    },
    "kp.m-team.cc": {profileApi: "mteam"},
    "audiences.me": {
      statusPageKeepsForm: true,
      signinBeforeLoadComplete: true,
      waitForSecurityChallenge: true,
      turnstileAttendance: true,
      attendanceDoneLabel: /^已签到$/,
      reuseRecentPage: true,
      navigationRetries: 2,
      transferLabel: /^(?:传输|傳輸|Transfer)$/i,
      profileSelector: '.site-userbar',
      levelFromProfileImage: true,
      levelFromProfileText: true,
      detailFillOnly: true,
      profileMetrics: {
        bonus: '.site-userbar__compact-metric--bonus',
        seedingPoints: '.site-userbar__compact-metric--seeding-bonus'
      }
    },
    "pt.keepfrds.com": {levelFromUserbar: true},
    "pt.btschool.club": {
      reuseRecentPage: true,
      navigationRetries: 2,
      attendanceUrl: "/index.php?action=addbonus"
    },
    "zhuque.in": {profileApi: "zhuque"},
    "rousi.pro": {profileApi: "rousi"},
    "rousi.zip": {profileApi: "rousi"},
    "sunnypt.top": {profileApi: "sunny"},
    "sewerpt.com": {
      reuseRecentPage: true,
      navigationRetries: 2,
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得金币\s*[\]】]?$/,
      profilePatterns: {
        bonus: /金币\s*(?:\[使用\])?\s*[:：]?\s*([\d,.]+)/
      },
      profileLabels: {
        bonus: /^金币$/
      }
    },
    "springsunday.net": {
      reuseRecentPage: true,
      navigationRetries: 2,
      profilePatterns: {
        bonus: /茉莉\s*[:：]?\s*([\d,.]+)/
      },
      profileLabels: {
        bonus: /^茉莉$/
      }
    },
    "hdarea.club": {
      inlineAttendance: true,
      profileRow: /^\s*欢迎回来/,
      attendanceDoneText: /\[\s*已签到\s*\]/
    },
    "ptchdbits.co": {
      refreshOnly: true,
      manualMessage: "CHDBits 签到需要人工答题，插件仅刷新账号数据"
    },
    "xingtan.one": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得杏仁\s*[\]】]?$/
    },
    "pt.xingyungept.org": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得星焱\s*[\]】]?$/,
      profilePatterns: {
        bonus: /星焱\s*(?:\[使用\])?\s*[:：]?\s*([\d,.]+)/
      },
      profileLabels: {
        bonus: /^星焱$/
      }
    },
    "open.cd": {imageCaptcha: "opencd", reuseRecentPage: true, manualMessage: "OpenCD 图片验证码未能可靠识别，请在网页中处理"},
    "u2.dmhy.org": {refreshOnly: true, manualMessage: "U2 签到需要人工验证，插件仅刷新账号数据"},
    "pttime.org": {
      attendanceQuery: true,
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^\s*签到领魔力\s*$/
    },
    "pterclub.net": {
      reuseRecentPage: true,
      navigationRetries: 2,
      inlineAttendance: true,
      inlineAttendanceSelector: "#do-attendance",
      attendanceLabel: /^\s*签到得猫粮\s*$/,
      attendanceDoneText: /[（(]?\s*签到已得\s*[\d,.]+\s*[）)]?/,
      profileRow: /欢迎回来/,
      profilePatterns: {
        bonus: /猫粮\s*(?:\[使用\s*\|\s*站免池\])?\s*[:：]?\s*([\d,.]+)/
      },
      profileLabels: {
        bonus: /^猫粮$/
      },
      levelPattern: /\b(Nexus\s*Master|Staff\s*Leader|Ultimate\s*User|Extreme\s*User|Crazy\s*User|Insane\s*User|Veteran\s*User|Elite\s*User|Power\s*User|Administrator|Moderator|Uploader|Sysop|Peasant|VIP|User)\b/i
    },
    "ptlgs.org": {
      reuseRecentPage: true,
      navigationRetries: 2,
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得工分\s*[\]】]?$/,
      profilePatterns: {
        bonus: /工分\s*(?:\[使用\])?\s*[:：]?\s*([\d,.]+)/
      },
      profileLabels: {
        bonus: /^工分$/
      }
    },
    "qingwapt.org": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得蝌蚪\s*[\]】]?$/
    },
    "hhanclub.net": {
      profileSelector: "#user-info-panel",
      levelFromProfileImage: true,
      refreshInNewPage: true,
      revealAttendanceSelector: "#user-avatar",
      reuseRecentPage: true,
      navigationRetries: 2,
      profilePatterns: {
        bonus: /憨豆\s*[:：]\s*([\d,.]+)/,
        ratio: /分享率\]?\s*[:：]\s*([\d,.]+|∞|Inf|无限|無限)/i
      },
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得憨豆\s*[\]】]?$/
    },
    "hxpt.org": {
      profileSelector: ".cute-top-profile",
      hiddenAttendanceSelector: ".cute-top-profile__dropdown a.cute-top-profile__attendance-link",
      homePaths: ["/"],
      refreshInNewPage: true,
      reuseRecentPage: true,
      navigationRetries: 2,
      profilePatterns: {bonus: /火花\s*(?:\[火花商店\]\s*)?(?:\[我的火花\]\s*)?[:：]\s*([\d,.]+)/},
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^\s*签到得火花\s*$/
    },
    "totheglory.im": {
      inlineAttendance: true,
      inlineAttendanceSelector: "#signed",
      attendanceDoneText: /[\[【]\s*已[签簽]到\s*[\]】]/,
      accountRow: /欢迎回来/,
      profileRow: /欢迎回来/
    },
    "hdcity.city": {
      profileSelector: "body",
      detailFillOnly: true,
      levelFromProfileImage: true,
      levelFromProfileText: true,
      reuseRecentPage: true,
      navigationRetries: 1,
      attendancePaths: ["/sign"],
      attendanceLabel: /^(?:assignment_turned_in)?\s*Check\s*in$/i,
      attendanceDoneLabel: /^(?:assignment_turned_in)?\s*Checked\s*in$/i
    },
    "hddolby.com": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^\s*签到得鲸币\s*$/
    },
    "crabpt.vip": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得蟹币\s*[\]】]?$/
    },
    "ptsbao.club": {
      reuseRecentPage: true,
      continueAttendanceForm: true,
      imageCaptcha: "ptsbao",
      manualMessage: "PTSBao 图片验证码未能可靠识别，请在网页中处理"
    },
    "ubits.club": {
      reuseRecentPage: true,
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得U币\s*[\]】]?$/i,
      accountRow: /欢迎回来/,
      profilePatterns: {
        bonus: /U币\s*(?:\[使用\])?\s*[:：]?\s*([\d,.]+)/i
      },
      profileLabels: {
        bonus: /^U币$/i
      }
    },
    "zmpt.cc": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得电力\s*[\]】]?$/,
      profilePatterns: {
        bonus: /电力值?\s*[:：]?\s*([\d,.]+)/i
      },
      profileLabels: {
        bonus: /^(?:电力值?|電力值?)$/
      }
    },
    "52pt.site": {
      continueAttendanceForm: true,
      nativeAttendanceNavigation: true,
      sliderCaptcha: "pt52",
      protectAttendanceForm: true,
      statusPageKeepsForm: true,
      attendanceEntryAliases: ["/52bakatestdate0823.php"],
      accountSelector: "#info_block a.User_Name[href]",
      attendancePaths: ["/bakatest.php", "/52bakatestdate0823.php"],
      attendanceLabel: /^[\[【]?\s*签到赚魔力\s*[\]】]?$/,
      statusPath: "/bakatest.php",
      manualSelector: "#slider-container, #slider-btn",
      manualMessage: "请在 52PT 签到页完成滑块并签到，再刷新结果",
      transferLabel: /^传输$/
    }
  };
  rules["pterclub.com"] = rules["pterclub.net"];
  function get(origin) {
    try {
      const target = new URL(origin);
      return target.protocol === "https:" && !target.port ? rules[target.hostname.replace(/^www\./, "")] || null : null;
    } catch { return null; }
  }
  const api = {get};
  root.NetSurfRules = api;
  if (typeof module !== "undefined") module.exports = api;
})(globalThis);
