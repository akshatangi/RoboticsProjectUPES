"""Builds Getting_Started_Guide.pdf in the project root (python-docx -> LibreOffice).

    python scripts/make_getting_started_pdf.py
"""
import os
import re
import shutil
import subprocess
import tempfile

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT, MONO = "Times New Roman", "Courier New"
doc = Document()
s = doc.sections[0]
s.page_width, s.page_height = Cm(21), Cm(29.7)
s.left_margin = s.right_margin = Cm(2.2)
s.top_margin = s.bottom_margin = Cm(2.0)
st = doc.styles["Normal"]
st.font.name, st.font.size = FONT, Pt(11.5)
st.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT)


def font(run, size=11.5, bold=False, italic=False, name=FONT, color=None):
    run.font.name, run.font.size, run.font.bold, run.font.italic = name, Pt(size), bold, italic
    rf = run._element.get_or_add_rPr().get_or_add_rFonts()
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), name)
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def shade(p, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), fill)
    p._p.get_or_add_pPr().append(shd)


def para(text="", size=11.5, bold=False, italic=False, after=5, align=None, keep=False):
    """Paragraph with **bold** and `code` markup."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after, pf.space_before, pf.line_spacing = Pt(after), Pt(0), 1.2
    pf.keep_with_next = keep
    if align:
        pf.alignment = align
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        if part.startswith("**"):
            font(p.add_run(part[2:-2]), size, True, italic)
        elif part.startswith("`"):
            font(p.add_run(part[1:-1]), size - 1.5, False, False, MONO)
        else:
            font(p.add_run(part), size, bold, italic)
    return p


def h1(text):
    para(text, 16, True, after=4, keep=True).paragraph_format.space_before = Pt(12)


def h2(text):
    para(text, 13, True, after=3, keep=True).paragraph_format.space_before = Pt(8)


def code(lines):
    for i, ln in enumerate(lines):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.space_after = Pt(6 if i == len(lines) - 1 else 0)
        pf.space_before = Pt(2 if i == 0 else 0)
        pf.line_spacing = 1.0
        pf.left_indent = Cm(0.4)
        pf.keep_with_next = i < len(lines) - 1
        shade(p, "EEF2F7")
        font(p.add_run(ln if ln else " "), 9.5, False, False, MONO,
             "5A6270" if ln.strip().startswith("#") else None)


def bullets(items):
    for it in items:
        p = para("\u2022  " + it, after=2)
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.first_line_indent = Cm(-0.4)


def box(text, fill="FFF4D6"):
    p = para(text, 11, after=8)
    shade(p, fill)
    p.paragraph_format.left_indent = Cm(0.2)
    p.paragraph_format.right_indent = Cm(0.2)


def table(header, rows, widths):
    """Cells starting with ` are printed in the monospace font."""
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        font(c.paragraphs[0].add_run(h), 10.5, True)
        shade(c.paragraphs[0], "DDE5F0")
    for r in rows:
        cells = t.add_row().cells
        for i, v in enumerate(r):
            cells[i].text = ""
            mono = v.startswith("`")
            font(cells[i].paragraphs[0].add_run(v.strip("`")), 9.5 if mono else 10.5, False, False,
                 MONO if mono else FONT)
    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Cm(w)
    lay = OxmlElement("w:tblLayout")
    lay.set(qn("w:type"), "fixed")
    t._tbl.tblPr.append(lay)
    for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), widths):
        gc.set(qn("w:w"), str(int(w * 567)))
    para("", after=2)


# ---------------------------------------------------------------- content
para("Getting Started Guide", 22, True, after=2, align=WD_ALIGN_PARAGRAPH.CENTER)
para("Networked Teleoperation of a Robot through Shell Commands", 13, after=2, align=WD_ALIGN_PARAGRAPH.CENTER)
para("How to set up, run and check the project on your own laptop", 11, italic=True, after=12,
     align=WD_ALIGN_PARAGRAPH.CENTER)

h1("What this project does (in one minute)")
para("You type commands like `move 1` or `turn 90` in a terminal (the **operator**). They travel over the "
     "network, either directly over **TCP** or through an **MQTT broker** (Mosquitto), to a simulated "
     "Pioneer P3-DX robot (the **robot server**). The robot executes them, stops itself in front of "
     "obstacles or if the connection dies, and sends its position back. So you always need "
     "**two terminals**: one for the robot, one for you.")
box("**Good to know:** the robot is simulated in pure Python (the \u201cmock\u201d backend), so you do NOT "
    "need CoppeliaSim to run anything. Add `--gui` to see the robot in a window (Step 3b). For the "
    "real simulator, see Step 8 (CoppeliaSim).")

h1("Step 1: Install (one time only)")
para("You need **Python 3.10 or newer**. Check it first:")
code(["python3 --version        # Linux / macOS", "py --version             # Windows"])
para("Open a terminal **inside the project folder** and create a virtual environment:", keep=True)
h2("Linux / macOS")
code(["cd \"Robotics project\"", "python3 -m venv .venv", "source .venv/bin/activate",
      "pip install -r requirements.txt"])
h2("Windows (PowerShell)")
code(["cd \"Robotics project\"", "py -m venv .venv", ".venv\\Scripts\\Activate.ps1",
      "pip install -r requirements.txt"])
bullets(["After activation your prompt starts with **(.venv)**. Activate it again in **every new terminal** "
         "you open (the `source ...` or `Activate.ps1` line).",
         "Windows says \u201cscripts are disabled\u201d? Run once: "
         "`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`",
         "Windows users: type `python` wherever this guide says `python3`.",
         "Linux: the simulation window needs Tk. If `--gui` fails, run `sudo apt install python3-tk`."])

h1("Step 2: First check that everything works (2 minutes)")
code(["python3 -m pytest"])
para("Expected: a line ending in **passed**. Without a broker, the MQTT tests are shown as "
     "**skipped**. That is fine. With a broker running (Step 4), all **68 tests pass**.")
box("**On Harsh's laptop (ROS installed):** pytest crashes with \u201cNo module named 'lark'\u201d because ROS is "
    "on PYTHONPATH. Use `env -u PYTHONPATH python3 -m pytest` instead (or open a terminal without ROS).")

h1("Step 3: Drive the robot over TCP (the main demo)")
h2("Terminal 1: start the robot")
code(["python3 -m teleop.server --backend mock --transport tcp --port 9000"])
para("You should see: `Robot server ready: backend=mock transport=tcp ...` Leave this terminal open.")
h2("Terminal 2: start the operator shell")
code(["python3 -m teleop.cli --transport tcp --host 127.0.0.1 --port 9000"])
para("You get a `teleop>` prompt. Try these one by one:", keep=True)
code(["teleop> ping              # checks the connection, prints the round-trip time",
      "teleop> status            # where is the robot? (x, y, heading, state)",
      "teleop> move 1            # drive 1 metre forward",
      "teleop> wait              # wait until the move has finished",
      "teleop> turn 90           # turn 90 degrees left",
      "teleop> goto 1 1          # drive to the point x=1, y=1",
      "teleop> vel 0.2 0         # drive at 0.2 m/s until told otherwise",
      "teleop> stop              # stop",
      "teleop> reset             # put the robot back at the start",
      "teleop> help              # list all commands",
      "teleop> quit              # leave"])
para("After each motion command you see an **ack** (accepted) and later a **result** such as "
     "`result #3 move: reached after 4.45 s, final error 0.025 m`.")
h2("Three things worth showing (they prove the safety layer works)")
table(["Try this", "What should happen"], [
    ["`macro macros/safety_demo.tlm`", "The robot drives at a box and stops by itself about 30 cm in front of it "
                                      "(state OBSTACLE), even though no stop was sent."],
    ["`vel 0.2 0` then close the shell window",
     "About 1 second later Terminal 1 prints \u201clink lost (watchdog): stopping robot\u201d."],
    ["Open a 3rd terminal and start a second shell", "It is refused: \u201crobot busy: another operator has "
                                                     "control\u201d. Only one driver at a time."],
], [6.2, 10.4])
box("**Tip:** Ctrl+C inside the shell is an **emergency stop**, not exit. Use `quit` to leave. "
    "Ctrl+C in Terminal 1 stops the robot server.", "E3F1E6")
para("Other ready-made command files: `macros/square.tlm`, `macros/goto_square.tlm`, "
     "`macros/health_check.tlm`, `macros/video_demo.tlm`. Run any of them with `macro <file>`.")

h1("Step 3b: Watch the robot move (simulation window for the video)")
para("Add **--gui** to the robot command. A window opens that shows the room, the robot, its sonar rays, "
     "the path it drove, the current goal and its state (grey IDLE, blue MOVING, orange OBSTACLE, "
     "red LINK_LOST), plus a log of every command it received.", keep=True)
code(["# terminal 1: robot WITH the simulation window",
      "python3 -m teleop.server --backend mock --transport tcp --port 9000 --gui",
      "",
      "# terminal 2: a ready-made 1.5-minute demo (or type commands yourself)",
      "python3 -m teleop.cli --port 9000 --script macros/video_demo.tlm"])
para("The demo drives a loop around the room with goto, then turn and move, and finally drives at the box "
     "without ever sending stop, so you can see the robot stop itself in front of it.")
table(["To record the screen on", "Do this"], [
    ["Ubuntu (GNOME)", "Press Ctrl+Shift+Alt+R to start and stop. The video goes to ~/Videos/Screencasts"],
    ["Windows", "Press Win+Alt+R (Xbox Game Bar) while the window is in front"],
    ["macOS", "Press Cmd+Shift+5 and choose \u201cRecord Selected Portion\u201d"],
    ["Any OS", "OBS Studio (free), or share the window in the Meet/Teams/Zoom call"],
], [5.0, 11.6])
box("**Tip:** close the simulation window to stop the robot server. `--gui` also works with "
    "`--transport mqtt`. For the course video you can simply share this window in the team meeting.",
    "E3F1E6")

h1("Step 4: Drive the robot over MQTT")
h2("4a. Install and start the Mosquitto broker")
table(["Your OS", "Install", "Start (from the project folder)"], [
    ["Ubuntu / Debian", "`sudo apt install mosquitto`", "`mosquitto -c config/mosquitto.conf -v`"],
    ["macOS", "`brew install mosquitto`", "`mosquitto -c config/mosquitto.conf -v`"],
    ["Windows", "installer from mosquitto.org (C:\\Program Files\\mosquitto)",
     "`mosquitto.exe -c config\\mosquitto.conf -v"],
], [3.0, 5.2, 8.4])
para("On Ubuntu the package may already run a broker on port 1883. If you get \u201caddress already in use\u201d, "
     "run `sudo systemctl stop mosquitto` first. Keep the broker terminal open.")
h2("4b. Robot and operator (two more terminals)")
code(["python3 -m teleop.server --backend mock --transport mqtt --qos 1 --gui",
      "python3 -m teleop.cli --transport mqtt --qos 1"])
para("Use the same commands as in Step 3. Use `--qos 0` on **both** sides to compare. To see the "
     "raw messages, open one more terminal and run `mosquitto_sub -h 127.0.0.1 -t 'teleop/#' -v`.")

h1("Step 5: Make the network bad on purpose")
para("The impairment proxy adds delay, jitter and packet loss between you and the robot. With the robot "
     "from Step 3 still running on port 9000:", keep=True)
code(["# terminal A: proxy 9001 -> robot 9000 (100 ms each way, 25 ms jitter, 1 % loss)",
      "python3 -m teleop.netem --listen 9001 --target 127.0.0.1:9000 \\",
      "        --delay 100 --jitter 25 --loss 0.01",
      "",
      "# terminal B: connect THROUGH the proxy",
      "python3 -m teleop.cli --transport tcp --port 9001",
      "teleop> rtt 20          # now about 200 ms instead of 1 ms",
      "teleop> goto 1 0        # still accurate, just starts later"])

h1("Step 6: Re-run the experiments (optional, about 15 minutes)")
para("This regenerates every number, table and plot used in the report. It needs **two brokers**: "
     "one normal (port 1883) and one with Nagle switched on (port 1885, only for the Nagle test).", keep=True)
code(["mosquitto -c config/mosquitto.conf                    # broker 1, port 1883",
      "# broker 2: copy the config, set 'listener 1885',",
      "#           and delete the set_tcp_nodelay line",
      "mosquitto -c my_nagle.conf",
      "",
      "python3 experiments/run_experiments.py --trials 10      # all 550 trials",
      "python3 experiments/pid_tuning.py                       # PID study",
      "python3 experiments/analyze.py                          # tables + figures"])
para("Quick look instead of the full run: "
     "`python3 experiments/run_experiments.py --scenarios S1_latency --trials 2`")
box("**Careful:** a quick run overwrites the CSV of that scenario in results/raw/. Run the full command "
    "again afterwards, or do your experiments on your own Git branch.")

h1("Step 7: Rebuild and check the report")
para("Needs **LibreOffice** installed (`soffice` must work in the terminal).", keep=True)
code(["python3 report/build_report.py      # makes the .docx and .pdf in report/",
      "python3 report/check_report.py      # checks format, citations, placeholders"])
para("The text of the report is in `report/content.py`. Edit **your own sections** there, then rebuild. "
     "`check_report.py` must end with **0 FAIL**. The WARN lines list the `<...>` placeholders "
     "(SAP IDs, Project/Group No., unit numbers, links) that still have to be filled in.")

h1("Step 8: Run it in CoppeliaSim (the real simulator, for the video)")
para("**1. Install CoppeliaSim Edu** (free for students) from coppeliarobotics.com/downloads. Linux: unpack the "
     "`.tar.xz` for your Ubuntu version, e.g. into `~/CoppeliaSim`. Windows: run the installer. "
     "macOS: open the `.dmg`.")
para("**2. Start CoppeliaSim** and leave it open. Do **not** press Play.", keep=True)
code(["~/CoppeliaSim/CoppeliaSim_Edu_V4_10_0_rev0_Ubuntu24_04/coppeliaSim.sh     # Linux",
      "# Windows: Start menu -> CoppeliaSim Edu      macOS: open coppeliaSim.app"])
para("**3. Start the robot server with the CoppeliaSim backend.** It loads our scene "
     "(`scenes/teleop_p3dx.ttt`: the P3-DX in the same room) by itself:", keep=True)
code(["python3 -m teleop.server --backend coppelia --transport tcp --port 9000"])
para("**4. Drive it** from a second terminal, by hand as in Step 3 or with the ready-made video demo:", keep=True)
code(["python3 -m teleop.cli --port 9000 --script macros/video_demo.tlm      # about 1 minute"])
para("**5. Record** the CoppeliaSim window (see the recording table in Step 3b) or share it in the team "
     "meeting. Stop the server with Ctrl+C. The simulation stops cleanly and you can start again at once.")
box("**Do not** open the scene with `coppeliaSim.sh -f`: the space in \u201cRobotics project\u201d breaks it. Let "
    "the server load the scene, or use File \u2192 Open scene. To rebuild the scene, open an empty scene and "
    "run `python3 scenes/build_scene.py`.")

h1("Where to find things")
table(["What", "Where"], [
    ["Robot code (server, controller, safety, transports)", "`teleop/"],
    ["Simulation window", "`teleop/viewer.py"],
    ["Tests", "`tests/"],
    ["Experiment scripts", "`experiments/"],
    ["Results: raw data, tables, figures", "`results/  (raw, tables, figures)"],
    ["Results explained in words", "`docs/RESULTS.md"],
    ["Full run guide with real outputs", "`docs/HOW_TO_RUN.md"],
    ["Your personal task list, commit plan, viva questions", "`docs/members/<Your_Name>.md"],
    ["Commit plan for everyone, Git rules", "`COMMIT_PLAN.md + docs/GIT_WORKFLOW.md"],
    ["Slides outline, demo script, submission checklist", "`docs/helpers/"],
    ["Report (Word + PDF)", "`report/"],
], [8.6, 8.0])

h1("If something goes wrong")
table(["Problem", "Fix"], [
    ["Could not connect ... 9000", "Start the robot server (Step 3, Terminal 1) first, same --port."],
    ["cannot reach MQTT broker", "Start Mosquitto (Step 4a)."],
    ["MQTT connects but robot never answers", "Same --qos and --robot-id on both sides."],
    ["robot busy: another operator has control", "Close the other shell, or wait 1 second."],
    ["Every command: REJECTED stale", "Robot and operator PCs have different clocks. Sync the time, "
                                       "or start the server with --max-cmd-age 5."],
    ["Robot stops by itself, state LINK_LOST", "Normal safety behaviour (no messages for 1 s). Send a new command."],
    ["--gui: no window / tkinter error", "Linux: sudo apt install python3-tk. Windows/macOS: reinstall Python "
                                         "from python.org (includes Tk)."],
    ["Address already in use", "An old server or broker is still running. Close it."],
    ["No module named 'lark' in pytest", "ROS is on PYTHONPATH. Run: env -u PYTHONPATH python3 -m pytest"],
], [6.6, 10.0])
para("More fixes: `docs/TROUBLESHOOTING.md`.", italic=True)

# ---------------------------------------------------------------- build
work = tempfile.mkdtemp()
dx = os.path.join(work, "Getting_Started_Guide.docx")
doc.save(dx)
soffice = shutil.which("soffice") or shutil.which("libreoffice")
with tempfile.TemporaryDirectory() as prof:
    subprocess.run([soffice, f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", "pdf",
                    "--outdir", work, dx], check=True, capture_output=True)
shutil.copy(os.path.join(work, "Getting_Started_Guide.pdf"), os.path.join(ROOT, "Getting_Started_Guide.pdf"))
print("written", os.path.join(ROOT, "Getting_Started_Guide.pdf"))
