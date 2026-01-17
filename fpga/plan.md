# FPGA folder plan + notes

## Goal
Keep the FPGA example “boring”:
- `route_fpga_with_widths.py` should be short and readable.
- Running it should reliably produce a DRC-clean board (internal DRC).
- Any “weirdness” should be fixed in the routing core, not in this script.

## Simplifications to keep
- Use `FourLayerFPGA` routing strategy with `net_layer_overrides` for the few nets where we care about the preferred layer (JTAG on `F.Cu`, dense nets on inners).
- Use `net_via_costs={"*": 2.0}` (global via cost). Note: this is a **per-net** override mechanism; it is not a “via type” cost table.
- Use `pcb_tool.api.check_internal_drc()` for internal DRC reporting (no regex parsing in scripts).

## Historical notes
The remainder of this file contains earlier board-design notes that were used as brainstorming input.

BOM (minimal bring-up)

Power

U1: Lattice LCMXO2-640HC-4MG132C (1)

FB1: Ferrite bead, 0603, ~600 Ω @ 100 MHz (optional) (1)

C_BULK1: 10 µF, X5R/X7R, 6.3 V+, 0805 (1)

C_BULK2: 22 µF, X5R/X7R, 6.3 V+, 0805 (optional) (1)


Decoupling (recommended starting point)

(Exact count depends on how many VCC/VCCIO balls you break out; this is a safe “small board” baseline.)

C_VCC_0V1: 0.1 µF, X7R, 6.3 V+, 0402/0603 (6)

C_VCCIO_0V1: 0.1 µF, X7R, 6.3 V+, 0402/0603 (12)

C_BANK_4V7: 4.7 µF, X5R/X7R, 6.3 V+, 0603/0805 (4)


JTAG

J1: 2×5 0.05" JTAG header (Cortex style) (1)

R_TCK: 33 Ω, 1%, 0402/0603 (1) (optional but recommended)

R_TMS: 33 Ω, 1%, 0402/0603 (1) (optional but recommended)

R_TDI: 33 Ω, 1%, 0402/0603 (1) (optional but recommended)


Configuration strap + reset

R_PROG: 10 kΩ, 1%, 0402/0603 (1) pull-up for PROGRAMN

R_INIT: 10 kΩ, 1%, 0402/0603 (1) pull-up for INITN

R_DONE: 10 kΩ, 1%, 0402/0603 (1) pull-up for DONE

SW1: Momentary pushbutton (PROGRAM), normally open (1)


Optional clock (if you want an external oscillator)

X1: 3.3 V CMOS oscillator (e.g., 12/16/24 MHz) (1)

R_CLK: 22 Ω or 33 Ω, 1%, 0402/0603 (1) series


Optional status LEDs (only if you want visual bring-up)

LED1/LED2: LED 0603 (2)

R_LED1/R_LED2: 1 kΩ–2.2 kΩ, 1%, 0402/0603 (2)



---

Simple CSV: “what is connected to what”

Copy/paste into a file like machxo2_min_board.csv.

Net,From,To,Notes
3V3_IN,Power_Connector:+3V3,FB1:IN,"Optional ferrite bead before FPGA rail"
3V3_FPGA,FB1:OUT,U1:VCC(all),"Tie all VCC balls to 3V3_FPGA"
3V3_FPGA,FB1:OUT,U1:VCCIO0(all),"Tie bank rail(s) to your I/O voltage; here assumed 3.3V"
3V3_FPGA,FB1:OUT,U1:VCCIO1(all),"If unused, still tie to valid rail"
3V3_FPGA,FB1:OUT,U1:VCCIO2(all),"If unused, still tie to valid rail"
3V3_FPGA,FB1:OUT,U1:VCCIO3(all),"If unused, still tie to valid rail"
GND,Power_Connector:GND,U1:GND(all),"All ground balls to solid ground plane"
3V3_FPGA,C_BULK1:1,GND:C_BULK1:2,"10uF bulk close to FPGA power entry"
3V3_FPGA,C_BULK2:1,GND:C_BULK2:2,"Optional 22uF bulk"
3V3_FPGA,C_VCC_0V1_x:1,GND:C_VCC_0V1_x:2,"0.1uF decouplers placed at VCC balls (repeat x times)"
3V3_FPGA,C_VCCIO_0V1_y:1,GND:C_VCCIO_0V1_y:2,"0.1uF decouplers placed at VCCIO balls (repeat y times)"
3V3_FPGA,C_BANK_4V7_b:1,GND:C_BANK_4V7_b:2,"4.7uF per bank or per cluster"

VTREF,J1:1,3V3_FPGA,"JTAG voltage reference"
GND,J1:2,GND,"JTAG ground"
TMS,J1:3,R_TMS:IN,"Series resistor recommended"
TMS,R_TMS:OUT,U1:TMS,"JTAG TMS pin"
GND,J1:4,GND,"JTAG ground"
TCK,J1:5,R_TCK:IN,"Series resistor recommended"
TCK,R_TCK:OUT,U1:TCK,"JTAG TCK pin"
GND,J1:6,GND,"JTAG ground"
TDO,U1:TDO,J1:7,"JTAG TDO pin"
GND,J1:8,GND,"JTAG ground"
TDI,J1:9,R_TDI:IN,"Series resistor recommended"
TDI,R_TDI:OUT,U1:TDI,"JTAG TDI pin"
GND,J1:10,GND,"JTAG ground"

PROGRAMN,3V3_FPGA,R_PROG:1,"Pull-up"
PROGRAMN,R_PROG:2,U1:PROGRAMN,"sysCONFIG PROGRAMN"
PROGRAMN,U1:PROGRAMN,SW1:1,"PROGRAM button to GND"
GND,SW1:2,GND,"PROGRAM button return"

INITN,3V3_FPGA,R_INIT:1,"Pull-up (INITN is open-drain during config)"
INITN,R_INIT:2,U1:INITN,"sysCONFIG INITN"
DONE,3V3_FPGA,R_DONE:1,"Pull-up (DONE is open-drain during config)"
DONE,R_DONE:2,U1:DONE,"sysCONFIG DONE"

CLK_EXT,X1:OUT,R_CLK:IN,"Optional external oscillator output"
CLK_EXT,R_CLK:OUT,U1:PCLKx,"Route to a primary clock pin (choose a valid PCLK ball)"
3V3_FPGA,X1:VCC,3V3_FPGA,"Oscillator supply"
GND,X1:GND,GND,"Oscillator ground"

INITN,3V3_FPGA,R_LED1:1,"Optional LED (one possible wiring; choose polarity as you like)"
INITN,R_LED1:2,LED1:A,"Optional LED indicator"
GND,LED1:K,GND,"Optional LED return"
DONE,3V3_FPGA,R_LED2:1,"Optional LED"
DONE,R_LED2:2,LED2:A,"Optional LED indicator"
GND,LED2:K,GND,"Optional LED return"

Important note (so you don’t get stuck)

For U1:TMS/TCK/TDI/TDO/PROGRAMN/INITN/DONE/PCLKx, you must fill in the actual MG132 ball names from the Lattice pinout file / Diamond export. Once you paste/upload that pinout, I can regenerate the CSV with exact ball coordinates (e.g., “U1 ball A3”) instead of symbolic pin names.
