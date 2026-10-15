(function (root) {
  const rules = {
    "kp.m-team.cc": {profileApi: "mteam"},
    "audiences.me": {
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
    "zhuque.in": {profileApi: "zhuque"},
    "rousi.pro": {profileApi: "rousi"},
    "rousi.zip": {profileApi: "rousi"},
    "sunnypt.top": {profileApi: "sunny"},
    "hdarea.club": {inlineAttendance: true},
    "xingtan.one": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得杏仁\s*[\]】]?$/
    },
    "open.cd": {refreshOnly: true, manualMessage: "OpenCD 签到可能需要图片验证码，插件仅刷新账号数据"},
    "u2.dmhy.org": {refreshOnly: true, manualMessage: "U2 签到需要人工验证，插件仅刷新账号数据"},
    "pttime.org": {
      attendanceQuery: true,
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^\s*签到领魔力\s*$/
    },
    "qingwapt.org": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得蝌蚪\s*[\]】]?$/
    },
    "hhanclub.net": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得憨豆\s*[\]】]?$/
    },
    "hxpt.org": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^\s*签到得火花\s*$/
    },
    "hdcity.city": {
      attendancePaths: ["/sign"],
      attendanceLabel: /^(?:assignment_turned_in)?\s*Check\s*in$/i
    },
    "hddolby.com": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^\s*签到得鲸币\s*$/
    },
    "crabpt.vip": {
      attendancePaths: ["/attendance.php"],
      attendanceLabel: /^[\[【]?\s*签到得蟹币\s*[\]】]?$/
    },
    "52pt.site": {
      refreshOnly: true,
      accountSelector: "#info_block a.User_Name[href]",
      attendancePaths: ["/bakatest.php", "/52bakatest0818.php", "/52bakatestdate0823.php"],
      attendanceLabel: /^[\[【]?\s*签到赚魔力\s*[\]】]?$/,
      statusPath: "/bakatest.php",
      manualSelector: "#slider-container, #slider-btn",
      manualMessage: "请在 52PT 签到页完成滑块并签到，再刷新结果",
      transferLabel: /^传输$/
    }
  };
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
