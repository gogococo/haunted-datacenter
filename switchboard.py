"""Haunted switchboard rules: routing is simulated; web research is real."""
VERSION='switchboard-v1'
GHOSTS={
 'pip':{'name':'Pip','protocol':'DNS','color':'#b6d8b2','request':'I have a name—crypt.local—but no address. Where does it live?','object':'terminal'},
 'edgar':{'name':'Edgar','protocol':'SMTP','color':'#e4b18b','request':'One letter for caretaker@crypt.local. One recipient. Why is the whole building reading it?','object':'printer'},
 'mabel':{'name':'Mabel','protocol':'MQTT','color':'#b9abd9','request':'Everyone subscribed to midnight/door needs my announcement. I know the topic, not their addresses.','object':'rack'},
}
PROTOCOLS=('SMTP','MQTT','DNS')
REACTIONS={
 ('pip','DNS'):('FOUND','crypt.local → 10.13.0.7. An address! I can finally stop asking.'),
 ('pip','SMTP'):('MISADDRESSED','The printer is writing “Dear WHERE IS CRYPT.LOCAL”. Pip has accidentally become correspondence.'),
 ('pip','MQTT'):('SHOUTING','Every speaker asks “HAS ANYONE SEEN CRYPT.LOCAL?” Loudly. Still no address.'),
 ('edgar','DNS'):('UNDELIVERED','Found a server. Still holding the letter. Edgar would like to speak to a manager.'),
 ('edgar','SMTP'):('DELIVERED','Letter delivered to the caretaker. Edgar: “Thank you for respecting basic boundaries.”'),
 ('edgar','MQTT'):('OVERSHARING','Every subscriber just got Edgar’s letter. “I SAID ONE RECIPIENT.”'),
 ('mabel','DNS'):('NOT FOUND','Name lookup failed: “everyone listening”. Mabel is now glaring at the directory.'),
 ('mabel','SMTP'):('PAPER JAM','The mail service asks for a recipient address. Mabel feeds it a topic. The printer screams.'),
 ('mabel','MQTT'):('PUBLISHED','Announcement published to midnight/door. Every matching subscriber replies: “BOO. Received.”'),
}
ARCHIVE=[
 {'title':'MQTT: the publish/subscribe messaging standard','url':'https://mqtt.org/','content':'Paraphrased rehearsal evidence: MQTT publishes messages to topics; a broker distributes messages to clients with matching subscriptions.','protocols':['MQTT']},
 {'title':'DNS — MDN Glossary','url':'https://developer.mozilla.org/en-US/docs/Glossary/DNS','content':'Paraphrased rehearsal evidence: DNS resolves domain names to IP addresses.','protocols':['DNS']},
 {'title':'SMTP — MDN Glossary','url':'https://developer.mozilla.org/en-US/docs/Glossary/SMTP','content':'Paraphrased rehearsal evidence: SMTP is used to send email messages.','protocols':['SMTP']},
]

def initial():return {'routes':{'pip':'SMTP','edgar':'MQTT','mabel':'DNS'},'results':[],'attempts':0,'ready':False}

def evaluate(routes):
 if not isinstance(routes,dict) or any(k not in GHOSTS for k in routes):raise ValueError('Connect only the three ghost cables on the board.')
 if any(p not in PROTOCOLS for p in routes.values()):raise ValueError('Connect cables to one of the three protocol sockets.')
 if len(set(routes.values()))!=len(routes):raise ValueError('Each socket takes one cable. Swap the connections on the board.')
 results=[]
 for identifier,ghost in GHOSTS.items():
  protocol=routes.get(identifier)
  status,line=REACTIONS[(identifier,protocol)] if protocol else ('UNPLUGGED','Still waiting for a connection.')
  results.append({'id':identifier,'name':ghost['name'],'protocol':protocol,'correct':protocol==ghost['protocol'],'status':status,'line':line})
 return {'routes':routes.copy(),'results':results,'ready':all(r['correct'] for r in results)}

def source_protocols(source):
 text=' '.join(str(source.get(k,'')) for k in ('title','url','content')).lower()
 found=[]
 for name in ('DNS','SMTP','MQTT'):
  if name.lower() in text:found.append(name)
 return found


def terminal_command(state,command):
 """Interpret a small game command language. Never execute a shell or network call."""
 import shlex
 if not isinstance(command,str) or len(command)>200:raise ValueError('Keep commands under 200 characters.')
 try:args=shlex.split(command.strip())
 except ValueError:return 'Unclosed quote. Type help for command examples.'
 if not args:return 'Type help to see the commands.'
 if args==['help']:
  return ('status                       Check the repair\n'
          'ghostctl apply               Apply the tested wiring\n'
          'mqtt publish <topic> OPEN    Send the door its opening message\n\n'
          'Alex: Mabel knows the topic. Yes, I put the door on the message broker.\n'
          'These are simulated game commands; no system shell is connected.')
 if args==['status']:
  return '\n'.join(f'{label}: {"OK" if value else "WAITING"}' for label,value in [
   ('Ghost services',state.get('board',{}).get('ready')),('Protocol research',state.get('board_citation')),
   ('Wiring applied',state.get('switchboard_applied')),('Door message',state.get('door_signal'))])
 if args==['ghostctl','apply']:
  if not state.get('board',{}).get('ready'):return 'APPLY BLOCKED: fix the switchboard and send a successful test signal first.'
  if not state.get('board_citation'):return 'APPLY BLOCKED: use Tavily on the old computer to find a reference for the topics/subscribers protocol.'
  state['switchboard_applied']=True
  return 'Wiring applied. Three ghost services online.\nDoor listener waiting. Publish OPEN to the topic in Mabel’s request.'
 if len(args)==4 and args[:2]==['mqtt','publish']:
  if not state.get('switchboard_applied'):return 'BROKER OFFLINE: run ghostctl apply after fixing and testing the wiring.'
  if args[2]!='midnight/door':return f'Published to {args[2]}. No door subscribed to that topic. Ask Mabel for the exact topic.'
  if args[3]!='OPEN':return 'Door received the message, but expects OPEN (capital letters).'
  state['door_signal']=True
  return 'Published OPEN → midnight/door\nDoor: message received. CLICK.\nThe exit is unlocked. Alex: “See? Enterprise architecture.”'
 return 'Unknown command. Try help. This haunted terminal only understands the commands listed there.'
