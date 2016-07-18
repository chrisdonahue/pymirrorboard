import signal
import sys
import time

import evdev

KEY_MIRROR = evdev.ecodes.KEY_SPACE
KEY_MIRROR_BURST_THRESH_S = 0.25

REMAPPING = {
  # number row
  'KEY_1': 'KEY_0',
  'KEY_2': 'KEY_9',
  'KEY_3': 'KEY_8',
  'KEY_4': 'KEY_7',
  'KEY_5': 'KEY_6',

  # first letter row
  'KEY_Q': 'KEY_P',
  'KEY_W': 'KEY_O',
  'KEY_E': 'KEY_I',
  'KEY_R': 'KEY_U',
  'KEY_T': 'KEY_Y',

  # second letter row
  'KEY_A': 'KEY_SEMICOLON',
  'KEY_S': 'KEY_L',
  'KEY_D': 'KEY_K',
  'KEY_F': 'KEY_J',
  'KEY_G': 'KEY_H',

  # third letter row
  'KEY_Z': 'KEY_SLASH',
  'KEY_X': 'KEY_DOT',
  'KEY_C': 'KEY_COMMA',
  'KEY_V': 'KEY_M',
  'KEY_B': 'KEY_N',

  # special keys
  'KEY_GRAVE': 'KEY_BACKSPACE',
  'KEY_CAPSLOCK': 'KEY_ENTER',
  'KEY_TAB': 'KEY_BACKSLASH'
}
REMAPPING_REV = {val: key for key, val in REMAPPING.items()}

mirrored = False
mirror_count = 0
mirror_start_time_last = None

class MirrorStateMachine(object):
  def __init__(self, mirror_key, mirror_key_burst_thresh=0.25):
    self.mirror_key = mirror_key
    self.mirror_key_burst_thresh = mirror_key_burst_thresh
    self.mirrored = False
    self.mirror_start_time_last = 0.0
    self.mirror_key_burst_thresh = mirror_key_burst_thresh
    self.keys_on = {True: set(), False: set()}

  def go_inside(self, event):
    if not self.mirrored:
      self.mirrored = True
      self.mirror_start_time_last = event.timestamp()
    else:
      print 'Warning: already inside mirror'
  
  def go_outside(self, event):
    if self.mirrored:
      self.mirrored = False
    else:
      print 'Warning: already outside mirror'

  def swallow_event(self, event):
    return []

  def pass_event(self, event):
    return [event]

  def is_burst_event(self, event):
    dt = event.timestamp() - self.mirror_start_time_last
    if not self.mirrored and dt < self.mirror_key_burst_thresh:
      print 'BURST! {}'.format(dt)
      return True
    return False

  def emit_mirror_key(self):
    events = []
    events.append(evdev.events.InputEvent(0, 0, evdev.ecodes.EV_KEY, self.mirror_key, 1))
    events.append(evdev.events.InputEvent(0, 0, evdev.ecodes.EV_KEY, self.mirror_key, 0))
    events.append(evdev.events.InputEvent(0, 0, evdev.ecodes.EV_SYN, evdev.ecodes.SYN_REPORT, 0))
    return events

  def mark_event(self, event):
    if event.code in self.keys_on[self.mirrored]:
      print 'Warning: attempt to mark already marked key'
    else:
      self.keys_on[self.mirrored].add(event.code)

  def unmark_event(self, event):
    if event.code not in self.keys_on[self.mirrored]:
      print 'Warning: attempt to unmark already unmarked key'
    else:
      self.keys_on[self.mirrored].remove(event.code)

  def is_marked(self, event):
    return event.code in self.keys_on[self.mirrored]

  def remap_event(self, event):
    event_key_name = evdev.ecodes.KEY[event.code]
    if event_key_name in REMAPPING_REV:
      event_key_name_remapped = REMAPPING_REV[event_key_name]
      event_key_id_remapped = getattr(evdev.ecodes, event_key_name_remapped)
      event.code = event_key_id_remapped
      print 'Remapping: {}->{}'.format(event_key_name, event_key_name_remapped)
    return [event]

  def handle_event(self, event):
    if event.type == evdev.ecodes.EV_KEY:
      if not self.mirrored:
        if event.value == 1:
          if event.code == KEY_MIRROR:
            self.go_inside(event)
            return self.swallow_event(event)
          else:
            self.mark_event(event)
            return self.pass_event(event)
        elif event.value == 0:
          if self.is_marked(event):
            self.unmark_event(event)
            return self.pass_event(event)
          else:
            self.unmark_event(event)
            return self.remap_event(event)
        elif event.value == 2:
          if self.is_marked(event):
            return self.pass_event(event)
          else:
            return self.remap_event(event)
      else:
        if event.value == 1:
          self.mark_event(event)
          return self.remap_event(event)
        elif event.value == 0:
          if event.code == KEY_MIRROR:
            self.go_outside(event)
            if self.is_burst_event(event):
              return self.emit_mirror_key()
            else:
              return self.swallow_event(event)
          else:
            if self.is_marked(event):
              self.unmark_event(event)
              return self.remap_event(event)
            else:
              return self.pass_event(event)
        elif event.value == 2:
          if event.code == KEY_MIRROR:
            return self.swallow_event(event)
          else:
            if self.is_marked(event):
              return self.remap_event(event)
            else:
              return self.pass_event(event)
      print 'Warning: Unhandled event logic for {}'.format(event)
    return self.pass_event(event)

if __name__ == '__main__':
  # list devices if not enough args
  if len(sys.argv) < 2:
    hw_devices = [evdev.InputDevice(fn) for fn in evdev.list_devices()]
    for i, hw_device in enumerate(hw_devices):
      print '{}:\t{}\t{}\t{}'.format(i, hw_device.fn, hw_device.name, hw_device.phys)
    sys.exit(0)

  # parse arguments
  hw_device_id = int(sys.argv[1])
  hw_device_path = evdev.list_devices()[hw_device_id]
  assert hw_device_path

  # init hardware countdown
  print 'Starting in 500ms'
  time.sleep(0.5)

  # init hw/sw devices
  hw_device = evdev.InputDevice(hw_device_path)
  assert hw_device != None
  sw_device = evdev.uinput.UInput()
  assert sw_device != None

  # register handler and grab device (exclusive)
  def signal_handler(signal, frame):
    global hw_device
    print 'Closing device: {}'.format(hw_device.name)
    hw_device.ungrab()
  signal.signal(signal.SIGINT, signal_handler)
  print 'Using device: {}'.format(hw_device.name)
  hw_device.grab()

  # create state machine
  sm = MirrorStateMachine(KEY_MIRROR, KEY_MIRROR_BURST_THRESH_S)

  # consume events
  for xevent in hw_device.read_loop():
    yevents = sm.handle_event(xevent)
    for event in yevents:
      sw_device.write_event(event)
