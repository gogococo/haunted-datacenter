"""Haunted switchboard rules: routing is simulated; web research is real."""
VERSION='switchboard-v2'
BROKER_HOST='crypt.local'
BROKER_IP='10.13.0.7'
DOOR_TOPIC='midnight/door'
GHOSTS={
 'pip':{'name':'Pip','protocol':'DNS','color':'#b6d8b2','request':'I have a name—crypt.local—but no address. Where does it live?','object':'terminal'},
 'edgar':{'name':'Edgar','protocol':'SMTP','color':'#e4b18b','request':'One letter for caretaker@crypt.local. One recipient. Why is the whole building reading it?','object':'printer'},
 'mabel':{'name':'Mabel','protocol':'MQTT','color':'#b9abd9','request':'Oh no. I forgot my topic! My door-update subscribers are waiting. I wrote it in my launch post. Could you fetch it?','object':'rack'},
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
 ('mabel','MQTT'):('CONNECTED','The broker recognizes Mabel. Her subscribers are waiting. Now find her missing topic and publish the update.'),
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
          'mosquitto_pub -h <host> -t <topic> -m OPEN\n'
          '                             Publish with the Mosquitto MQTT client\n\n'
          '-h = broker host (Pip found its name/address)\n'
          '-t = topic (read Mabel’s bookmarked post)\n'
          '-m = message (the door expects OPEN)\n\n'
          'Send OPEN to the door topic. Mabel accepts no substitutions.')
 if args==['mosquitto_pub','--help']:
  return 'Mosquitto MQTT publisher\nUsage: mosquitto_pub -h HOST -t TOPIC -m MESSAGE\n-h / --host: broker hostname\n-t / --topic: exact topic name, without + or # wildcards\n-m / --message: message payload\nAsk Pip for the host; fetch Mabel’s launch post for the topic.'
 if args==['status']:
  return '\n'.join(f'{label}: {"OK" if value else "WAITING"}' for label,value in [
   ('Ghost services',state.get('board',{}).get('ready')),('Protocol research',state.get('board_citation')),
   ('Announcement subscription',state.get('subscription',{}).get('passed')),('Mabel’s post retrieved',state.get('topic_evidence')),('Wiring applied',state.get('switchboard_applied')),('Door message',state.get('door_signal'))])
 if args==['ghostctl','apply']:
  if not state.get('board',{}).get('ready'):return 'APPLY BLOCKED: fix the switchboard and send a successful test signal first.'
  if not state.get('board_citation'):return 'APPLY BLOCKED: inspect a wildcard reference with Tavily on the old computer.'
  if not state.get('subscription',{}).get('passed'):return 'APPLY BLOCKED: repair Mabel’s announcement subscription at the switchboard. Private mail must stay private.'
  state['switchboard_applied']=True
  return 'Wiring applied. Three ghost services online.\nMosquitto MQTT client ready. Publish OPEN to the topic in Mabel’s launch post. Type mosquitto_pub --help for the flags.'
 if args[0]=='mosquitto_pub':
  names={'-h':'host','--host':'host','-t':'topic','--topic':'topic','-m':'message','--message':'message'}
  flags={}
  if len(args)!=7:return 'Usage: mosquitto_pub -h HOST -t TOPIC -m MESSAGE. Type mosquitto_pub --help.'
  for flag,value in zip(args[1::2],args[2::2]):
   if flag not in names or names[flag] in flags:return 'Use each of -h, -t and -m once. Type mosquitto_pub --help.'
   flags[names[flag]]=value
  if not state.get('switchboard_applied'):return 'BROKER OFFLINE: run ghostctl apply after fixing and testing the wiring.'
  if flags['host'] not in (BROKER_HOST,BROKER_IP):return 'No broker found at that host. Pip’s successful DNS lookup has the broker name and address.'
  if not state.get('topic_evidence'):return 'TOPIC UNVERIFIED: read Mabel’s bookmarked post on the old computer first.'
  if any(c in flags['topic'] for c in '+#'):return 'Publish to an exact topic name. + and # are subscription filters, not publish topics.'
  if flags['topic']!=DOOR_TOPIC:return 'Message sent, but no door is listening on that topic. Check the door-update entry in Mabel’s post.'
  if flags['message']!='OPEN':return 'Door received the message, but expects OPEN (capital letters).'
  state['door_signal']=True
  return 'Mosquitto → '+flags['host']+' · Published OPEN → '+DOOR_TOPIC+'\nDoor: message received. CLICK.\nThe exit is unlocked. Alex: “See? Enterprise architecture.”'
 return 'Unknown command. Try help. This haunted terminal only understands the commands listed there.'

ANNOUNCEMENTS=[
 {'topic':'midnight/door/announcement','message':'Mabel: door maintenance starts at midnight.','wanted':True,'ghost':'mabel'},
 {'topic':'midnight/cooling/announcement','message':'Pip: coolant delivery is on its way.','wanted':True,'ghost':'pip'},
 {'topic':'midnight/mail/private','message':'Edgar’s private letter. Again.','wanted':False,'ghost':'edgar'},
 {'topic':'midnight/cooling/debug/trace','message':'DEBUG: pump thinks it is a printer.','wanted':False,'ghost':'edgar'},
 {'topic':'daylight/door/announcement','message':'Day shift rota. Nobody here is on it.','wanted':False,'ghost':'mabel'},
 {'topic':'midnight/announcement','message':'Retired announcement channel. Please stop resurrecting it.','wanted':False,'ghost':'pip'},
]

def topic_matches(filter,topic):
 if not isinstance(filter,str) or not filter or len(filter)>120 or '\x00' in filter:raise ValueError('Enter an MQTT subscription filter.')
 parts=filter.split('/')
 for i,part in enumerate(parts):
  if ('#' in part and (part!='#' or i!=len(parts)-1)) or ('+' in part and part!='+'):raise ValueError('Wildcards occupy a whole topic level. # must be the last level.')
 if topic.startswith('$') and parts[0] in ('+','#'):return False
 levels=topic.split('/');j=0
 for part in parts:
  if part=='#':return True
  if j>=len(levels) or part not in ('+',levels[j]):return False
  j+=1
 return j==len(levels)

def test_subscription(filter):
 filter=str(filter).strip();results=[{**x,'received':topic_matches(filter,x['topic'])} for x in ANNOUNCEMENTS]
 passed=all(x['received']==x['wanted'] for x in results)
 missed=sum(x['wanted'] and not x['received'] for x in results);noise=sum(not x['wanted'] and x['received'] for x in results)
 return {'filter':filter,'passed':passed,'results':results,'message':'Only the midnight service announcements reach the speaker. Edgar: “An astonishingly basic improvement.”' if passed else f'{missed} announcement(s) missed. {noise} private, debug or off-shift message(s) broadcast. Edgar would like a word.'}
