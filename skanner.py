#!/usr/bin/env python3
"""Hent offentlig kurskalender. Bare eksakt datospesifikk instruktørmatch publiseres."""
import asyncio, datetime as dt, json, re, sys
from pathlib import Path
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright
HERE=Path(__file__).resolve().parent
OUT=HERE/"docs/kurs.json"
NAME="Kristoffer Sandal"
URLS=["https://www.proffkurs.no/produkt/fse/","https://www.proffkurs.no/fse-kurs-for-instruert-personell/"]
MONTHS={"jan":1,"januar":1,"feb":2,"februar":2,"mar":3,"mars":3,"apr":4,"april":4,"mai":5,"jun":6,"juni":6,"jul":7,"juli":7,"aug":8,"august":8,"sep":9,"sept":9,"september":9,"okt":10,"oktober":10,"nov":11,"november":11,"des":12,"desember":12}
DATERE=re.compile(r"(\d{1,2})\s*\.?\s*("+ "|".join(sorted(MONTHS,key=len,reverse=True))+r")\s*[,]?\s*(20\d\d)",re.I)
TIME=re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
ADDRESS=re.compile(r"([A-ZÆØÅ][^\n]{2,95}?\b\d{1,3}[A-Za-z]?\s*,\s*\d{4}\s+[A-ZÆØÅa-zæøå -]{2,50})")
def parse(text,url,now=None):
    if not text or len(text)>16000 or NAME.casefold() not in text.casefold():return None
    if "Info om kurset" not in text or "Bestill kurs" not in text:return None
    lines=[re.sub(r"\s+"," ",s).strip() for s in text.splitlines() if s.strip()]
    header=next(((i,m) for i,s in enumerate(lines[:12]) if (m:=DATERE.search(s))),None)
    if not header:return None
    i,m=header
    try: day=dt.date(int(m[3]),MONTHS[m[2].lower()],int(m[1]))
    except ValueError:return None
    if day < (now or dt.datetime.now(ZoneInfo("Europe/Oslo")).date()):return None
    title=" ".join(s for s in lines[i+1:i+4] if len(s)<95 and not re.search(r"^(kr|åpent|fullt|tidsrom)",s,re.I)).strip()
    if not re.search(r"FSE|BA4|instruert personell|førstehjelp",title,re.I):return None
    timematch=TIME.search(lines[i])
    if not timematch and "Tidsrom" in text:timematch=TIME.search(text.split("Tidsrom",1)[1][:140])
    addr=ADDRESS.search(text[:1500])
    if not timematch or not addr:return None
    if re.search(r"\b(avlyst|fullbooket|utsolgt)\b"," ".join(lines[i+1:i+9]),re.I):return None
    clock=f"{int(timematch[1]):02d}:{timematch[2]}"
    kind="Instruert personell / BA4" if re.search("BA4|instruert personell",title,re.I) else "Praktisk førstehjelp" if "førstehjelp" in title.lower() and "fse" not in title.lower() else "FSE lavspenning og førstehjelp"
    return {"id":day.isoformat()+"-"+clock.replace(":","")+"-"+re.sub("[^a-z0-9]","-",kind.lower()),"dato":day.isoformat(),"tid":clock,"navn":title,"adresse":addr[1].strip(),"kurs":kind,"lenke":url}
JS="""() => {
 const visible=e=>{let r=e.getBoundingClientRect();let s=getComputedStyle(e);return r.width>140&&r.height>100&&s.visibility!=='hidden'};
 let nodes=[...document.querySelectorAll('[role=dialog],[aria-modal=true],.el-dialog,.am-dialog,[class*=modal],[class*=Modal],[class*=popup]')].filter(e=>visible(e)&&/Info om kurset/.test(e.innerText||'')&&/Bestill kurs/.test(e.innerText||'')&&(e.innerText||'').length<16000);
 if(!nodes.length){for(let e of document.querySelectorAll('h1,h2,h3,h4,span,div')){if(e.children.length||e.textContent.trim()!=='Info om kurset')continue;for(let p=e.parentElement,n=0;p&&n<8;p=p.parentElement,n++){let t=p.innerText||'';if(visible(p)&&t.includes('Bestill kurs')&&t.length<16000){nodes.push(p);break}}}}
 nodes.sort((a,b)=>a.innerText.length-b.innerText.length);
 return nodes[0]?.innerText||null;
}"""
async def main():
 if "--fixture" in sys.argv:
    sample=(HERE/"tests/modal_example.txt").read_text()
    assert parse(sample,URLS[0],dt.date(2026,10,1))
    assert parse(sample.replace(NAME,"Niklas Sæthre"),URLS[0],dt.date(2026,10,1)) is None
    print("Filtertest OK");return 0
 found={};opened=0
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  try:
   for url in URLS:
    page=await browser.new_page(locale="nb-NO",timezone_id="Europe/Oslo")
    try:
     resp=await page.goto(url,wait_until="domcontentloaded",timeout=55000)
     if not resp or resp.status>=400:raise RuntimeError("HTTP "+str(resp.status if resp else "unknown"))
     await page.wait_for_timeout(4000)
     # Booking plugins can render in iframes.
     for frame in page.frames:
      try:
       locator=frame.get_by_text("Les mer og bestill",exact=False)
       count=min(await locator.count(),100)
       if count:print(url,"buttons",count,"frame",frame.url[:110])
       for j in range(count):
        try:
         await locator.nth(j).click(timeout=6500)
         await page.wait_for_timeout(1800)
         detail=await frame.evaluate(JS)
         if not detail and frame != page.main_frame:detail=await page.evaluate(JS)
         if detail:
          opened+=1
          event=parse(detail,url)
          if event:found[event["id"]]=event;print("MATCH",event["dato"],event["tid"],event["navn"])
          else:
           print("NO_MATCH", "frame",frame.url[:100],"len",len(detail),"name",NAME.lower() in detail.lower(),"date",bool(DATERE.search(detail)),"first300",repr(detail[:300]),"last400",repr(detail[-400:]))
         await page.keyboard.press("Escape")
         await page.wait_for_timeout(250)
         # If escape doesn't dismiss, use common close buttons.
         if await frame.evaluate(JS):
          for s in ['button[aria-label="Close"]','button[aria-label="Lukk"]','button:has-text("Lukk")']:
           try:
            b=frame.locator(s).last
            if await b.is_visible(timeout=300):await b.click(timeout=1500);break
           except Exception:pass
        except Exception as ex:
         print("Event error",str(ex)[:200])
         try:await page.keyboard.press("Escape")
         except Exception:pass
      except Exception as ex:print("Frame error",str(ex)[:200])
    except Exception as ex:print("Page error",url,str(ex)[:250])
    finally:await page.close()
  finally:await browser.close()
 print("Scanned dialogs",opened,"confirmed events",len(found))
 if not opened:
  print("ERROR: No course dialogs read; preserving previous JSON");return 2
 if not found:
  print("ERROR: No instructor matches; preserving previous JSON until checked");return 3
 data={"updated_at":dt.datetime.now(ZoneInfo("Europe/Oslo")).isoformat(timespec="seconds"),"source":"proffkurs.no","filter":"instruktør per kursdato","events":sorted(found.values(),key=lambda e:(e["dato"],e["tid"]))}
 OUT.parent.mkdir(parents=True,exist_ok=True)
 OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
 print("Saved",OUT);return 0
if __name__=="__main__":raise SystemExit(asyncio.run(main()))
