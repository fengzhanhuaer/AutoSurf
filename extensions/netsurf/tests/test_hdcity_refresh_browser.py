from pathlib import Path
import asyncio
import json
import shutil
from urllib.parse import urlsplit

import pytest
from playwright.async_api import async_playwright


@pytest.mark.asyncio
async def test_hdcity_uses_own_details_when_homepage_is_slow(tmp_path):
    source = Path(__file__).resolve().parents[1]
    extension = tmp_path / "extension"
    shutil.copytree(source, extension, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    manifest = json.loads((extension / "manifest.json").read_text(encoding="utf-8"))
    manifest["host_permissions"] = ["https://*/*"]
    (extension / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    html = '''<div class="button-group"><a href="userdetails"><strong>fixture</strong>[Elite Angel]
        <i class="material-icons" title="Ratio:">assessment</i>607.44 <i class="material-icons" title="Uploaded:">arrow_upward</i>307.11 GB
        <i class="material-icons" title="Downloaded:">arrow_downward</i>517.71 MB</a>
        <a href="sign"><i>assignment_turned_in</i>Checked in</a><a href="mybonus"><i>flare</i>815953<span>Bonus</span></a></div>
        <div class="text"><b>Invited By</b><a href="userdetails?id=9">other user<span>Uploaded: 999 TB Downloaded: 2 TB Ratio: 999999 Karma Points: 999999</span></a></div>
        <div class="text"><strong>Uploaded:</strong> 307.11 GB <strong>Downloaded:</strong> 517.71 MB <strong>Sharing Ratio:</strong> 607.441</div>
        <div class="text"><b>Karma Points</b> 815953.0</div>'''
    requests = []
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(str(tmp_path / "profile"),
            channel="chromium", headless=True,
            args=[f"--disable-extensions-except={extension}", f"--load-extension={extension}"])
        try:
            async def respond(route):
                path = urlsplit(route.request.url).path
                requests.append((route.request.method, path))
                assert route.request.method == "GET" and path != "/sign"
                if path != "/userdetails":
                    await asyncio.sleep(7)
                    await route.fulfill(status=504, body="timeout")
                else:
                    await route.fulfill(content_type="text/html; charset=utf-8", body=html)
            await context.route("https://hdcity.city/**", respond)
            worker = context.service_workers[0] if context.service_workers else await context.wait_for_event("serviceworker")
            await worker.evaluate("""async () => {
                await chrome.storage.local.set({autoEnabled:false,
                  sites:Object.fromEntries(sites.catalog.map(s=>[s.id,{enabled:s.id==='hdcity.city'}])),scheduleConfig:{timeout:5},
                  'verifiedDay:hdcity.city':today(),
                  'operation:hdcity.city':{day:today(),awaitingConfirmation:false,startedAt:123},
                  'lastResult:hdcity.city':{status:'already_done',verified:true,confirmedDay:today(),message:'今日已签到',profile:{uploaded:'306.47 GB'}}});
                await reschedule();
            }""")
            result = await worker.evaluate("async () => await inspectSite('hdcity.city',true)")
            assert result["refreshState"]["status"] == "success"
            assert result["profile"] == {"level":"Elite Angel", "bonus":"815953.0", "uploaded":"307.11 GB", "downloaded":"517.71 MB", "ratio":"607.441", "seedingPoints":None}
            state = await worker.evaluate("async () => await readState('hdcity.city')")
            assert state["lastResult"]["status"] == "already_done"
            assert state["operation"]["startedAt"] == 123
            assert requests and all(path == "/userdetails" for _, path in requests)
            assert len(context.pages) == 1
        finally:
            await context.close()
