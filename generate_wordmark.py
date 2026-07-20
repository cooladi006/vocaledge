#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Regenerates sys/wm_dark.png (and the other approved colorways) using the
EXACT unmodified logic from BRAND-GENERATOR.md (Drive: 02_Brand/BRAND-GENERATOR.md).
Only change from the canonical script: font path points at the local
fonts/ folder bundled with this repo (the original pointed at
/usr/share/fonts/truetype/google-fonts/, which only exists on the ATLAS
sandbox, not on a fresh deploy host). No drawing logic was altered.
"""
from PIL import Image, ImageDraw, ImageFont
import os

GF = os.path.join(os.path.dirname(__file__), "fonts") + "/"
BOLD = GF + "Poppins-Bold.ttf"
INK=(23,25,29); TEAL=(14,107,96); TEALL=(127,196,186); PAPER=(250,250,248); WHITE=(255,255,255); GREY=(120,124,128)
S=3

def F(px): return ImageFont.truetype(BOLD, px*S)

def rising_E(d,x,y,h,color):
    st=int(h*0.15)
    d.rounded_rectangle([x,y,x+st,y+h],radius=st*0.15,fill=color)
    for arm_y,ln in [(0,0.42),(0.5,0.55),(1.0,0.72)]:
        yy=y+int((h-st)*arm_y)
        d.rounded_rectangle([x,yy,x+int(h*ln),yy+st],radius=st*0.15,fill=color)
    return int(h*0.72)

def wordmark(filename,bg,tcolor,ecolor,W=1600,H=520,size=150,track=-6):
    img=Image.new("RGB",(W*S,H*S),bg); d=ImageDraw.Draw(img)
    fL=F(size); tr=track*S
    def tw(t):
        w=0
        for ch in t:
            b=d.textbbox((0,0),ch,font=fL); w+=(b[2]-b[0])+tr
        return w
    cap=int(size*0.72*S); e_w=int(cap*0.72); gap=int(size*0.06*S)
    total=tw("Vocal")+gap+e_w+gap+tw("dge")
    asc,desc=fL.getmetrics()
    x=(W*S-total)//2; ty=(H*S-asc)//2
    cx=x
    for ch in "Vocal":
        d.text((cx,ty),ch,font=fL,fill=tcolor); b=d.textbbox((0,0),ch,font=fL); cx+=(b[2]-b[0])+tr
    cx+=gap
    rising_E(d,cx,ty+(asc-cap),cap,ecolor); cx+=e_w+gap
    for ch in "dge":
        d.text((cx,ty),ch,font=fL,fill=tcolor); b=d.textbbox((0,0),ch,font=fL); cx+=(b[2]-b[0])+tr
    img.resize((W,H),Image.LANCZOS).save(filename)

if __name__ == "__main__":
    out_dir = os.path.join(os.path.dirname(__file__), "sys")
    os.makedirs(out_dir, exist_ok=True)
    # Only wm_dark.png is actually consumed by app.py's generate_card(), but
    # produce the light variant too since it's cheap and may be useful later.
    wordmark(os.path.join(out_dir, "wm_dark.png"), INK, WHITE, TEALL)   # dark surface (used by the card)
    wordmark(os.path.join(out_dir, "wm_light.png"), PAPER, INK, TEAL)  # light surface (default)
    print("wordmark assets built in", out_dir)
