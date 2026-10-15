(function (root) {
  const catalog = [
  {
    "id": "1ptba.com",
    "name": "1PTBA",
    "domain": "1ptba.com",
    "origin": "https://1ptba.com",
    "hosts": [
      "1ptba.com",
      "www.1ptba.com"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "52pt.site",
    "name": "52PT",
    "domain": "52pt.site",
    "origin": "https://52pt.site",
    "hosts": [
      "52pt.site",
      "www.52pt.site"
    ],
    "signinPath": "/bakatest.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "agsvpt.com",
    "name": "Arctic Global Seed Vault",
    "domain": "agsvpt.com",
    "origin": "https://www.agsvpt.com",
    "hosts": [
      "www.agsvpt.com",
      "agsvpt.com"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "audiences.me",
    "name": "Audiences",
    "domain": "audiences.me",
    "origin": "https://audiences.me",
    "hosts": [
      "audiences.me",
      "www.audiences.me"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "carpt.net",
    "name": "CarPT",
    "domain": "carpt.net",
    "origin": "https://carpt.net",
    "hosts": [
      "carpt.net",
      "www.carpt.net"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "crabpt.vip",
    "name": "CrabPT",
    "domain": "crabpt.vip",
    "origin": "https://crabpt.vip",
    "hosts": [
      "crabpt.vip",
      "www.crabpt.vip"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "cyanbug.net",
    "name": "CyanBug",
    "domain": "cyanbug.net",
    "origin": "https://cyanbug.net",
    "hosts": [
      "cyanbug.net",
      "www.cyanbug.net"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "discfan.net",
    "name": "DiscFan",
    "domain": "discfan.net",
    "origin": "https://discfan.net",
    "hosts": [
      "discfan.net",
      "www.discfan.net"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "et8.org",
    "name": "TCCF",
    "domain": "et8.org",
    "origin": "https://et8.org",
    "hosts": [
      "et8.org",
      "www.et8.org"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "profile",
    "homePath": "/index.php"
  },
  {
    "id": "gamegamept.com",
    "name": "GGPT",
    "domain": "gamegamept.com",
    "origin": "https://www.gamegamept.com",
    "hosts": [
      "www.gamegamept.com",
      "gamegamept.com"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "haidan.cc",
    "name": "Haidan",
    "domain": "haidan.cc",
    "origin": "https://www.haidan.cc",
    "hosts": [
      "www.haidan.cc",
      "haidan.cc",
      "haidan.video"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hdarea.club",
    "name": "HDArea",
    "domain": "hdarea.club",
    "origin": "https://hdarea.club",
    "hosts": [
      "hdarea.club",
      "www.hdarea.club"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hdchina.org",
    "name": "HDChina",
    "domain": "hdchina.org",
    "origin": "https://hdchina.org",
    "hosts": [
      "hdchina.org",
      "www.hdchina.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hdcity.city",
    "name": "HDCity",
    "domain": "hdcity.city",
    "origin": "https://hdcity.city",
    "hosts": [
      "hdcity.city",
      "www.hdcity.city"
    ],
    "signinPath": "/sign",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hddolby.com",
    "name": "HD Dolby",
    "domain": "hddolby.com",
    "origin": "https://www.hddolby.com",
    "hosts": [
      "www.hddolby.com",
      "hddolby.com"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hdfans.org",
    "name": "HDFans",
    "domain": "hdfans.org",
    "origin": "https://hdfans.org",
    "hosts": [
      "hdfans.org",
      "www.hdfans.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hdhome.org",
    "name": "HDHome",
    "domain": "hdhome.org",
    "origin": "https://hdhome.org",
    "hosts": [
      "hdhome.org",
      "www.hdhome.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hdkyl.in",
    "name": "HDKylin",
    "domain": "hdkyl.in",
    "origin": "https://www.hdkyl.in",
    "hosts": [
      "www.hdkyl.in",
      "hdkyl.in"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hdsky.me",
    "name": "HDSky",
    "domain": "hdsky.me",
    "origin": "https://hdsky.me",
    "hosts": [
      "hdsky.me",
      "www.hdsky.me"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hdtime.org",
    "name": "HDTime",
    "domain": "hdtime.org",
    "origin": "https://hdtime.org",
    "hosts": [
      "hdtime.org",
      "www.hdtime.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hdvideo.top",
    "name": "HDVideo",
    "domain": "hdvideo.top",
    "origin": "https://hdvideo.top",
    "hosts": [
      "hdvideo.top",
      "www.hdvideo.top"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hhanclub.net",
    "name": "HhanClub",
    "domain": "hhanclub.net",
    "origin": "https://hhanclub.net",
    "hosts": [
      "hhanclub.net",
      "www.hhanclub.net",
      "hhan.club",
      "hhanclub.top"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "htpt.cc",
    "name": "HaitangPT",
    "domain": "htpt.cc",
    "origin": "https://www.htpt.cc",
    "hosts": [
      "www.htpt.cc",
      "htpt.cc"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "hxpt.org",
    "name": "HXPT",
    "domain": "hxpt.org",
    "origin": "https://www.hxpt.org",
    "hosts": [
      "www.hxpt.org",
      "hxpt.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "jpopsuki.eu",
    "name": "JPopsuki",
    "domain": "jpopsuki.eu",
    "origin": "https://jpopsuki.eu",
    "hosts": [
      "jpopsuki.eu",
      "www.jpopsuki.eu"
    ],
    "signinPath": "/",
    "profilePath": "/bonus.php",
    "mode": "profile",
    "homePath": "/index.php"
  },
  {
    "id": "kp.m-team.cc",
    "name": "M-Team",
    "domain": "kp.m-team.cc",
    "origin": "https://kp.m-team.cc",
    "hosts": [
      "kp.m-team.cc",
      "www.kp.m-team.cc"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "profile",
    "homePath": "/"
  },
  {
    "id": "kufei.org",
    "name": "KuFei",
    "domain": "kufei.org",
    "origin": "https://kufei.org",
    "hosts": [
      "kufei.org",
      "www.kufei.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "monikadesign.uk",
    "name": "MonikaDesign",
    "domain": "monikadesign.uk",
    "origin": "https://monikadesign.uk",
    "hosts": [
      "monikadesign.uk",
      "www.monikadesign.uk"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "profile",
    "homePath": "/index.php"
  },
  {
    "id": "nanyangpt.com",
    "name": "NanyangPT",
    "domain": "nanyangpt.com",
    "origin": "https://nanyangpt.com",
    "hosts": [
      "nanyangpt.com",
      "www.nanyangpt.com"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "profile",
    "homePath": "/index.php"
  },
  {
    "id": "open.cd",
    "name": "OpenCD",
    "domain": "open.cd",
    "origin": "https://open.cd",
    "hosts": [
      "open.cd",
      "www.open.cd"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "oshen.win",
    "name": "OshenPT",
    "domain": "oshen.win",
    "origin": "https://www.oshen.win",
    "hosts": [
      "www.oshen.win",
      "oshen.win"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "ourbits.club",
    "name": "OurBits",
    "domain": "ourbits.club",
    "origin": "https://ourbits.club",
    "hosts": [
      "ourbits.club",
      "www.ourbits.club"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "pandapt.net",
    "name": "PANDA",
    "domain": "pandapt.net",
    "origin": "https://pandapt.net",
    "hosts": [
      "pandapt.net",
      "www.pandapt.net"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "piggo",
    "name": "PigGo",
    "domain": "piggo.me",
    "origin": "https://piggo.me",
    "hosts": [
      "piggo.me",
      "www.piggo.me"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "pt.0ff.cc",
    "name": "Free Farm",
    "domain": "pt.0ff.cc",
    "origin": "https://pt.0ff.cc",
    "hosts": [
      "pt.0ff.cc",
      "www.pt.0ff.cc"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "pt.btschool.club",
    "name": "BTSchool",
    "domain": "pt.btschool.club",
    "origin": "https://pt.btschool.club",
    "hosts": [
      "pt.btschool.club",
      "www.pt.btschool.club"
    ],
    "signinPath": "/index.php?action=addbonus",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "pt.eastgame.org",
    "name": "TLFBits",
    "domain": "pt.eastgame.org",
    "origin": "https://pt.eastgame.org",
    "hosts": [
      "pt.eastgame.org",
      "www.pt.eastgame.org"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "profile",
    "homePath": "/index.php"
  },
  {
    "id": "pt.hdupt.com",
    "name": "HDU PT",
    "domain": "pt.hdupt.com",
    "origin": "https://pt.hdupt.com",
    "hosts": [
      "pt.hdupt.com",
      "www.pt.hdupt.com"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "pt.keepfrds.com",
    "name": "KEEPFRDS",
    "domain": "pt.keepfrds.com",
    "origin": "https://pt.keepfrds.com",
    "hosts": [
      "pt.keepfrds.com",
      "www.pt.keepfrds.com"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "profile",
    "homePath": "/index.php"
  },
  {
    "id": "pt.soulvoice.club",
    "name": "SoulVoice",
    "domain": "pt.soulvoice.club",
    "origin": "https://pt.soulvoice.club",
    "hosts": [
      "pt.soulvoice.club",
      "www.pt.soulvoice.club"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "pt.xingyungept.org",
    "name": "XingYunGePT",
    "domain": "pt.xingyungept.org",
    "origin": "https://pt.xingyungept.org",
    "hosts": [
      "pt.xingyungept.org",
      "www.pt.xingyungept.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "ptcafe.club",
    "name": "PTCafe",
    "domain": "ptcafe.club",
    "origin": "https://ptcafe.club",
    "hosts": [
      "ptcafe.club",
      "www.ptcafe.club"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "ptchdbits.co",
    "name": "CHDBits",
    "domain": "ptchdbits.co",
    "origin": "https://ptchdbits.co",
    "hosts": [
      "ptchdbits.co",
      "www.ptchdbits.co"
    ],
    "signinPath": "/bakatest.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "pterclub.net",
    "name": "PterClub",
    "domain": "pterclub.net",
    "origin": "https://pterclub.net",
    "hosts": [
      "pterclub.net",
      "www.pterclub.net",
      "pterclub.com"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "pthome.net",
    "name": "PTHome",
    "domain": "pthome.net",
    "origin": "https://pthome.net",
    "hosts": [
      "pthome.net",
      "www.pthome.net"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "ptlgs.org",
    "name": "PTLGS",
    "domain": "ptlgs.org",
    "origin": "https://ptlgs.org",
    "hosts": [
      "ptlgs.org",
      "www.ptlgs.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "ptskit.org",
    "name": "PTSKIT",
    "domain": "ptskit.org",
    "origin": "https://www.ptskit.org",
    "hosts": [
      "www.ptskit.org",
      "ptskit.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "pttime.org",
    "name": "PTTime",
    "domain": "pttime.org",
    "origin": "https://www.pttime.org",
    "hosts": [
      "www.pttime.org",
      "pttime.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "ptsbao.club",
    "name": "PTSBao",
    "domain": "ptsbao.club",
    "origin": "https://ptsbao.club",
    "hosts": [
      "ptsbao.club",
      "www.ptsbao.club"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "qingwapt.org",
    "name": "QingwaPT",
    "domain": "qingwapt.org",
    "origin": "https://www.qingwapt.org",
    "hosts": [
      "www.qingwapt.org",
      "qingwapt.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "rousi.pro",
    "name": "Rousi",
    "domain": "rousi.pro",
    "origin": "https://rousi.pro",
    "hosts": [
      "rousi.pro",
      "www.rousi.pro",
      "rousi.zip"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/"
  },
  {
    "id": "sewerpt.com",
    "name": "SewerPT",
    "domain": "sewerpt.com",
    "origin": "https://sewerpt.com",
    "hosts": [
      "sewerpt.com",
      "www.sewerpt.com"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "springsunday.net",
    "name": "SSD",
    "domain": "springsunday.net",
    "origin": "https://springsunday.net",
    "hosts": [
      "springsunday.net",
      "www.springsunday.net"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "profile",
    "homePath": "/index.php"
  },
  {
    "id": "sunnypt.top",
    "name": "SunnyPT",
    "domain": "sunnypt.top",
    "origin": "https://sunnypt.top",
    "hosts": [
      "sunnypt.top",
      "www.sunnypt.top"
    ],
    "signinPath": "/user/attendance",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/"
  },
  {
    "id": "tangpt.top",
    "name": "TangPT",
    "domain": "tangpt.top",
    "origin": "https://www.tangpt.top",
    "hosts": [
      "www.tangpt.top",
      "tangpt.top"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "tjupt.org",
    "name": "TJUPT",
    "domain": "tjupt.org",
    "origin": "https://tjupt.org",
    "hosts": [
      "tjupt.org",
      "www.tjupt.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "totheglory.im",
    "name": "TTG",
    "domain": "totheglory.im",
    "origin": "https://totheglory.im",
    "hosts": [
      "totheglory.im",
      "www.totheglory.im"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "u2.dmhy.org",
    "name": "U2",
    "domain": "u2.dmhy.org",
    "origin": "https://u2.dmhy.org",
    "hosts": [
      "u2.dmhy.org",
      "www.u2.dmhy.org"
    ],
    "signinPath": "/",
    "profilePath": null,
    "mode": "profile",
    "homePath": "/index.php"
  },
  {
    "id": "ubits.club",
    "name": "UBits",
    "domain": "ubits.club",
    "origin": "https://ubits.club",
    "hosts": [
      "ubits.club",
      "www.ubits.club"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "v6.nexushd.org",
    "name": "NexusHD",
    "domain": "v6.nexushd.org",
    "origin": "https://v6.nexushd.org",
    "hosts": [
      "v6.nexushd.org",
      "www.v6.nexushd.org"
    ],
    "signinPath": "/signin.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "xingtan.one",
    "name": "XingTan",
    "domain": "xingtan.one",
    "origin": "https://xingtan.one",
    "hosts": [
      "xingtan.one",
      "www.xingtan.one"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "yemapt.org",
    "name": "YemaPT",
    "domain": "yemapt.org",
    "origin": "https://www.yemapt.org",
    "hosts": [
      "www.yemapt.org",
      "yemapt.org"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  },
  {
    "id": "zhuque.in",
    "name": "Zhuque",
    "domain": "zhuque.in",
    "origin": "https://zhuque.in",
    "hosts": [
      "zhuque.in",
      "www.zhuque.in"
    ],
    "signinPath": "/",
    "profilePath": "/user/info",
    "mode": "profile",
    "homePath": "/user/info"
  },
  {
    "id": "zmpt.cc",
    "name": "ZhiMengPT",
    "domain": "zmpt.cc",
    "origin": "https://zmpt.cc",
    "hosts": [
      "zmpt.cc",
      "www.zmpt.cc"
    ],
    "signinPath": "/attendance.php",
    "profilePath": null,
    "mode": "signin",
    "homePath": "/index.php"
  }
];
  root.NetSurfCatalog = catalog;
  if (typeof module !== "undefined") module.exports = catalog;
})(globalThis);
