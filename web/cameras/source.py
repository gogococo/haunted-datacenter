"""Optional developer asset generator; requires Pillow. Game runtime uses shipped PNGs."""
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
root=Path(__file__).resolve().parent
font=next((str(p) for p in [Path('/System/Library/Fonts/Menlo.ttc'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf')] if p.exists()),None)
def f(s):return ImageFont.truetype(font,s) if font else ImageFont.load_default()
for idx,(name,zone) in enumerate([('west','GPU RACK'),('east','COOLING LOOP'),('crypt','EXIT DOOR')]):
 im=Image.new('RGB',(960,600),'#101c2a');d=ImageDraw.Draw(im)
 d.polygon([(0,0),(960,0),(650,370),(310,370)],fill='#1c3044')
 d.polygon([(0,600),(960,600),(650,370),(310,370)],fill='#263e50')
 for x in range(-600,1500,160):d.line([(480,350),(x,600)],fill='#456075',width=2)
 for y in (400,455,535):d.line([(0,y),(960,y)],fill='#456075',width=2)
 for side in (0,1):
  for k in range(4):
   x=(30+k*75) if side==0 else (800-k*60);y=80+k*42;w=140-k*18;h=350-k*55
   d.rectangle((x,y,x+w,y+h),fill='#142533',outline='#577184',width=3)
   for row in range(6):
    ry=y+16+row*(h-25)//6;d.rectangle((x+8,ry,x+w-8,ry+22),fill='#293d4b',outline='#354f62')
    for led in range(3):d.ellipse((x+w-22-led*12,ry+7,x+w-17-led*12,ry+12),fill='#c7a475' if k==0 else '#82c3ad')
 d.rectangle((370,145,590,370),fill='#26323f',outline='#809097',width=4)
 d.rectangle((395,166,565,205),fill='#101d26');d.text((408,173),zone,font=f(21),fill='#e4d8b1')
 if name=='west':
  import math
  for cx in (430,530):
   d.ellipse((cx-35,230,cx+35,300),fill='#101b22',outline='#759ba0',width=4)
   for angle in (0,120,240):
    x=cx+int(26*math.cos(math.radians(angle)));y=265+int(26*math.sin(math.radians(angle)))
    d.line((cx,265,x,y),fill='#789c9c',width=12)
   d.ellipse((cx-6,259,cx+6,271),fill='#c9d5bb')
  d.rectangle((389,315,571,353),fill='#a4463e',outline='#e0a26e',width=2)
  d.text((399,324),'FAN FAULT / HOT',font=f(18),fill='#ffe1b2')
  for x in (405,470,540):d.line([(x,135),(x-8,115),(x+6,95),(x,75)],fill='#e8a578',width=4)
 elif name=='east':
  d.ellipse((160,410,810,565),fill='#54a6bf',outline='#d9f5f2',width=4)
  for x,y in [(270,470),(500,520),(690,460)]:d.arc((x-50,y-12,x+50,y+12),0,190,fill='#91b7c5',width=2)
  d.line([(580,230),(660,230),(660,315)],fill='#a2bdc8',width=15)
  d.line([(657,313),(637,355),(674,399),(650,456)],fill='#b7f0ff',width=12)
  for x,y in [(695,335),(613,367),(707,398),(616,430)]:
   d.polygon([(x,y-12),(x-7,y+5),(x,y+10),(x+7,y+5)],fill='#c5f7ff')
  for x in (230,410,570,740):d.arc((x-36,466,x+36,484),0,300,fill='#def5ef',width=3)
 else:
  d.rectangle((385,230,575,350),fill='#2a3742',outline='#7d919d',width=4)
  d.rectangle((435,260,525,320),fill='#985a4c');d.text((447,279),'LOCK',font=f(20),fill='#f9d7ac')
  d.ellipse((650,250,730,335),fill='#9db5bb');d.polygon([(650,290),(730,290),(730,365),(712,350),(690,367),(670,350),(650,365)],fill='#9db5bb')
  d.ellipse((670,282,679,296),fill='#15232d');d.ellipse((700,282,709,296),fill='#15232d')
 d.rectangle((0,0,960,51),fill='#0c151d');d.text((24,13),f'CAM 0{idx+1} / {zone}   |   NIGHT SHIFT',font=f(21),fill='#bed2d0')
 d.ellipse((914,19,926,31),fill='#e27e68')
 im.save(root/(name+'.png'))
print('Three camera images created.')
