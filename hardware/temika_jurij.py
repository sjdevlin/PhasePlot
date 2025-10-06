		#!/bin/python

# 18.3.2025
# This is my first written python program after one day of learning python. You can do it better.
# Jurij

# Parameter to modify
# START
# Number of capilaries
capilaries = 2
# High temperature
temperature_high = 55
# Low temperature
temperature_low = 25
# Heating time
heating_time = "0:0:10"
# Temperature step for cooling
temperature_step = 0.5
# Cycle time
cycle_time = "0:1:00"
# Illumination enable
illumination_enable = 0x20
# Camera name
camera_name = "Genicam FLIR Blackfly S BFS-U3-70S7M 0159F410"
#END

# Open and configure a socket
import socket
HOST = "127.0.0.1"  # The server's hostname or IP address
PORT = 60000  # The port used by the server
sock = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
sock.connect( (HOST, PORT) )
sock.settimeout( 1. )
reply = sock.recv( 1024 )

# Send a script command function
def script_send_command( command, reply_wait ):
# command (string): temika's command
# reply_wait (boolean): Wheather to wait for a reply from temika.
	sock.sendall( command )
	if reply_wait:
		reply = sock.recv( 1024 )
		length = len( reply )
		while reply[length-2:] != b"\n\r": # Waiting for termination
			print( reply[length-2:] )
			reply += sock.recv( 1024 )
			length = len( reply )
		return reply

# Get X,Y,Z,A position
def script_get_position():
	script_send_command( b'<microscopeone>', False )
    
	# X
	script_send_command( b'<stepper axis="x">', True )
	reply = script_send_command( b'<status></status>', True )
	script_send_command( b'</stepper>', False )
	x = reply.split()
	x = float( x[3] )
    
	# Y
	script_send_command( b'<stepper axis="y">', True )
	reply = script_send_command( b'<status></status>', True )
	script_send_command( b'</stepper>', False )
	y = reply.split()
	y = float( y[3] )
    
	# Z
	script_send_command( b'<stepper axis="z">', True )
	reply = script_send_command( b'<status></status>', True )
	script_send_command( b'</stepper>', False )
	z = reply.split()
	z = float( z[3] )
    
	# A
	script_send_command( b'<stepper axis="a">', True )
	reply = script_send_command( b'<status></status>', True )
	script_send_command( b'</stepper>', False )
	a = reply.split()
	a = float( a[3] )
    
	script_send_command( b'</microscopeone>', False )
    
	return [x, y, z, a]


# Print move to a predefined position
def script_print_move( vec ):
	file.write( "\t<microscopeone>\n" )
    
	# Disable Afocus
	file.write( "\t\t<afocus>\n" )
	file.write( "\t\t\t<enable>OFF</enable>\n" )
	file.write( "\t\t</afocus>\n" )

	# Move to a new position
	# X
	file.write( "\t\t<stepper axis=\"x\">\n" )
	file.write( f"\t\t\t<move_absolute>{vec[0]} 10000</move_absolute>\n")
	file.write( "\t\t</stepper>\n" )
	# Y
	file.write( "\t\t<stepper axis=\"y\">\n" )
	file.write( f"\t\t\t<move_absolute>{vec[1]} 10000</move_absolute>\n")
	file.write( "\t\t</stepper>\n" )
	# Z
	file.write( "\t\t<stepper axis=\"z\">\n" )
	file.write( f"\t\t\t<move_absolute>{vec[2]} 100</move_absolute>\n" )
	file.write( "\t\t</stepper>\n" )
	# A
	file.write( "\t\t<stepper axis=\"a\">\n" )
	file.write( f"\t\t\t<move_absolute>{vec[3]} 10000</move_absolute>\n" )
	file.write( "\t\t</stepper>\n" )
    
	# Wait for the end of movement
	# X
	file.write( "\t\t<stepper axis=\"x\">\n" )
	file.write( "\t\t\t<wait_moving_end></wait_moving_end>\n" )
	file.write( "\t\t</stepper>\n\n" )
	# Y
	file.write( "\t\t<stepper axis=\"y\">\n" )
	file.write( "\t\t\t<wait_moving_end></wait_moving_end>\n" )
	file.write( "\t\t</stepper>\n\n" )
	# Z
	file.write( "\t\t<stepper axis=\"z\">\n" )
	file.write( "\t\t\t<wait_moving_end></wait_moving_end>\n" )
	file.write( "\t\t</stepper>\n\n" )
	# A
	file.write( "\t\t<stepper axis=\"a\">\n" )
	file.write( "\t\t\t<wait_moving_end></wait_moving_end>\n" )
	file.write( "\t\t</stepper>\n\n" )
    
	# Enable Afocus and wait for a lock
	file.write( "\t\t<afocus>\n" )
	file.write( "\t\t\t<enable>ON</enable>\n" )
	file.write( "\t\t\t<wait_lock>0.2 10.3</wait_lock>\n" )  
	file.write( "\t\t</afocus>\n" )
    
	file.write( "\t</microscopeone>\n" )


def script_print_capillary( filename, positions, number ):
	file.write( "<!-- Image all positions in a capillary -->\n" )
    
	file.write( "\t<!-- Start recording. -->\n" )
	file.write( "\t<save>\n" )
	file.write( f"\t\t<header>\n{filename}\nNumber of positions {number}, dark image, fluorescent image pairs.\n\t\t</header>\n" )
	file.write( f"\t\t<basename>{filename}</basename>\n" )
	file.write( "\t\t<append>DATE</append>\n" )
	file.write( "\t</save>\n" )
	file.write( f'\t<camera name="{camera_name}">\n' )
	file.write( "\t\t<record>ON</record>\n" )
	file.write( "\t</camera>\n" )
	file.write( "\t<microscopeone>\n" )
	file.write( "\t\t<record>ON</record>\n" )
	file.write( "\t</microscopeone>\n\n" )
    
	file.write( "\t<!-- Move to a position and acquire a dark image and a fluorescent image -->\n" )
	i = 0
	while i < number:
		vec = positions[i]
		script_print_move( vec )
		file.write( "\t<microscopeone>\n" )
		file.write( "\t\t<illumination><enable>0</enable></illumination>\n" )
		file.write( "\t</microscopeone>\n" )
		file.write( f'\t<camera name="{camera_name}">\n' )
		file.write( "\t\t<send_trigger></send_trigger>\n" )
		file.write( "\t</camera>\n" )
		file.write( "\t<microscopeone>\n" )
		file.write( f"\t\t<illumination><enable>{illumination_enable}</enable></illumination>\n" )
		file.write( "\t</microscopeone>\n" )
		file.write( f'\t<camera name="{camera_name}">\n' )
		file.write( "\t\t<send_trigger></send_trigger>\n" )
		file.write( "\t</camera>\n\n" )
		i += 1
   	 
	file.write( "\t<!-- Stop recording. -->\n" )
	file.write( f'\t<camera name="{camera_name}">\n' )
	file.write( "\t\t<record>OFF</record>\n" )
	file.write( "\t</camera>\n" )
	file.write( "\t<microscopeone>\n" )
	file.write( "\t\t<record>OFF</record>\n" )
	file.write( "\t</microscopeone>\n\n" )  
   	 
    

# Get positions
script_send_command( b"<temika>", False )

print( "p -- Save position\nf -- Finish capillary\n" )
i = 0
number = [0] # Number of positions per capillary
positions = [] # All [X,Y,Z,A] positions
while i < capilaries:
	key = input()
	if key == 'p':
		vec = script_get_position()
		number[i] += 1
		positions.append( vec )
		print( "capillary", i, vec )
	elif key == 'f':
		number.append( 0 )
		i += 1
		print( "p -- Save position\nf -- Finish capillary\n" );
i = 0
index = 0
while i < capilaries:
	print( "capillary ", i )
	j = 0
	while j < number[i]:
		print( "	position ", j, positions[j+index] )
		j += 1
	index += number[i]
	i += 1

script_send_command( b"</temika>", False )


# Open a scriptfile and print full script
file = open( "scriptfile.xml", "w" )
file.write( "<temika>\n" )

file.write( "<!-- Set temperature_high and wait heating_time -->\n" )
file.write( "\t<microscopeone>\n" )
file.write( '\t\t<pwr number="0">\n' )
file.write( "\t\t\t<feedback>\n" )   	 
file.write( f"\t\t\t\t<set>{temperature_high}</set>\n" )
file.write( "\t\t\t\t<enable>ON</enable>\n" )    
file.write( "\t\t\t</feedback>\n" )
file.write( "\t\t</pwr>\n" )
file.write( "\t</microscopeone>\n" )
file.write( f"\t<sleep>{heating_time}</sleep>\n\n" )

# Do the ramp
temperature = temperature_high
while temperature >= temperature_low:
	file.write( "<timestamp>0</timestamp>\n" )
    
	#Do the cycle
	i = 0
	index = 0
	while i < capilaries:
		script_print_capillary( f"capillary{i}_temperature{temperature}", positions[index:], number[i] )
		index += number[i]
		i += 1
    
	# Step down in temperature
	temperature -= temperature_step
	file.write( "\t<microscopeone>\n" )
	file.write( '\t\t<pwr number="0">\n' )
	file.write( "\t\t\t<feedback>\n" )   	 
	file.write( f"\t\t\t\t<set>{temperature}</set>\n" )
	file.write( "\t\t\t</feedback>\n" )
	file.write( "\t\t</pwr>\n" )
	file.write( "\t</microscopeone>\n" )
	file.write( f'\t<sleep timestamp="0">{cycle_time}</sleep>\n\n' )

file.write( "</temika>\n" )
file.close()



