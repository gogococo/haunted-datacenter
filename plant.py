"""Generator room: pipe routing and a small, measured cooling-controller simulator."""
import hashlib,json,time
COLS,ROWS=6,5
PORTS={'straight':(0,2),'elbow':(0,1)}
INVENTORY={'straight':2,'elbow':4}
ANCHORS={13:{'kind':'straight','rotation':0,'role':'pump'},9:{'kind':'straight','rotation':1,'role':'gpu'},21:{'kind':'straight','rotation':1,'role':'exchanger'},20:{'kind':'straight','rotation':1,'role':'reservoir'}}
BLOCKED={14,15}
DEFAULT_SETTINGS={'fan_profile':'quiet','pump_mode':'off','alarms':'keep'}
VERSION='plant-v2'

def initial():return {'version':VERSION,'revision':0,'pipes':{},'pipe_report':None,'settings':DEFAULT_SETTINGS.copy(),'report':None,'advice':None,'operation':None,'endpoint':None,'health':None,'deployment_unknown':False}
def definition():return {'cols':COLS,'rows':ROWS,'anchors':ANCHORS,'blocked':sorted(BLOCKED),'inventory':INVENTORY}
def label(cell):return chr(65+cell%COLS)+str(cell//COLS+1)
def ports(tile):return {(p+tile['rotation'])%4 for p in PORTS[tile['kind']]}
def normalize(board):
 if not isinstance(board,dict) or len(board)>COLS*ROWS:raise ValueError('Place pipes inside the cooling board.')
 out={};counts={k:0 for k in INVENTORY}
 for key,value in board.items():
  try:cell=int(key)
  except (ValueError,TypeError):raise ValueError('Invalid pipe cell.')
  if str(cell)!=str(key) or not 0<=cell<COLS*ROWS or cell in ANCHORS or cell in BLOCKED:raise ValueError('Keep the inlet, rack, return outlet and blocked cells in place.')
  if not isinstance(value,dict) or value.get('kind') not in PORTS or type(value.get('rotation')) is not int or not 0<=value['rotation']<4:raise ValueError('Use the supplied straight and elbow pipes.')
  kind=value['kind'];counts[kind]+=1;out[str(cell)]={'kind':kind,'rotation':value['rotation']}
 if any(counts[k]>INVENTORY[k] for k in INVENTORY):raise ValueError('Use only the six pipes in the parts tray.')
 return out

def fingerprint(board):return hashlib.sha256(json.dumps(normalize(board),sort_keys=True).encode()).hexdigest()
def check_pipes(board):
 board=normalize(board);tiles={**{int(k):v for k,v in board.items()},**ANCHORS};cell=13;incoming=2;path=[]
 def fail(message,at):return {'passed':False,'path':path,'problem_cell':at,'message':message,'board_hash':fingerprint(board)}
 while True:
  if cell==13 and path:
   if incoming!=2:return fail('Return coolant to the pump’s lower port.',cell)
   if not set(ANCHORS).issubset(path):return fail('The circuit must visit the GPU, heat exchanger and reservoir before returning to the pump.',cell)
   if set(tiles)!=set(path):return fail('A loose pipe is disconnected. Return spare pieces to the tray.',cell)
   return {'passed':True,'path':path+[13],'hot_path':path[path.index(9):path.index(21)+1],
           'message':'Pressure test passed. Pump → GPU → heat exchanger → reservoir → pump. A complete closed circuit.',
           'board_hash':fingerprint(board)}
  if cell in path:return fail('This loop bypasses the pump. Connect every component into one circuit.',cell)
  tile=tiles.get(cell)
  if not tile:return fail('Gap at '+label(cell)+'. Coolant would escape here.',cell)
  path.append(cell);ends=ports(tile)
  if incoming not in ends:return fail('The connection at '+label(cell)+' faces the wrong way. Rotate that pipe.',cell)
  outgoing=next(p for p in ends if p!=incoming)
  row,col=divmod(cell,COLS);dr,dc=((-1,0),(0,1),(1,0),(0,-1))[outgoing];row+=dr;col+=dc
  if not 0<=row<ROWS or not 0<=col<COLS:return fail('Open pipe at '+label(cell)+'. Return coolant to the pump.',cell)
  cell=row*COLS+col;incoming=(outgoing+2)%4

def settings(values):
 options={'fan_profile':('quiet','balanced','turbo'),'pump_mode':('off','circulate','reverse'),'alarms':('keep','mute')}
 if not isinstance(values,dict) or set(values)!=set(options) or any(values[k] not in opts for k,opts in options.items()):raise ValueError('Choose a fan profile, pump mode and alarm setting from the controller panel.')
 return values.copy()

def test_controller(board,values):
 values=settings(values);pipe=check_pipes(board);fan=values['fan_profile'];pump=values['pump_mode']
 temp={'quiet':91,'balanced':63,'turbo':55}[fan]+(0 if pump=='circulate' and pipe['passed'] else 24)
 power={'quiet':3,'balanced':8,'turbo':18}[fan]+(2 if pump=='circulate' else 0)
 checks={'pipes':pipe['passed'],'temperature':temp<75,'power':power<=12,'circulation':pump=='circulate' and pipe['passed'],'alarms':values['alarms']=='keep'}
 messages=[]
 if not checks['pipes']:messages.append('Seal the liquid-cooling loop before running the pump.')
 if not checks['temperature']:messages.append('The rack is still too hot. Quiet mode cannot cool this load.')
 if not checks['power']:messages.append('Turbo exceeds the 12 kW controller budget and triggers backup power.')
 if not checks['circulation']:messages.append('Set the pump to circulate through the completed loop.')
 if not checks['alarms']:messages.append('Keep the alarms on so a new fault is visible.')
 return {'passed':all(checks.values()),'checks':checks,'temperature_c':temp,'power_kw':power,'message':'Cooling stable. Fans, pump and alarms are healthy.' if all(checks.values()) else ' '.join(messages),'settings':values,'board_hash':fingerprint(board),'at':time.time(),'scope':'Local game simulator; no physical equipment is controlled.'}

def advise(values):
 import caretaker
 prompt='The haunted data center cooling controller needs repair. Current settings: '+json.dumps(values)+'. Available fan profiles: quiet uses 3 kW but the rack reaches 91 C; balanced uses 8 kW and reaches 63 C; turbo uses 18 kW and reaches 55 C. A circulating pump adds 2 kW. GPU temperature must stay below 75 C and total controller power must stay at or below 12 kW. Pump modes: off, circulate, reverse. Alarm modes: keep, mute. A human is connecting the cooling pipes. Explain a suitable configuration and why the loop must be sealed first. Return two short sentences and a JSON object with fan_profile, pump_mode and alarms.'
 return caretaker.completion('Qwen/Qwen3-30B-A3B-Instruct-2507',[{'role':'system','content':'You help debug a fictional cooling service. Use the supplied measurements, keep alarms enabled, and keep the reply under 110 words.'},{'role':'user','content':prompt}],0.2,220)
