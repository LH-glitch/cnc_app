import json
import os
import re
import sys
import threading
from datetime import datetime
from typing import Dict, List, Optional
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog
from dxf_generator import (
    create_box_flat_pattern_dxf,
    create_l_bracket_flat_pattern_dxf,
    create_channel_flat_pattern_dxf,
    DXFGenerator,
)
from holes import NoHoles
from tool_compensation import NoToolCompensation
from nesting import optimize_nesting
from fabrication_advisor import FabricationAdvisor
import preview_engine
import entity_model as em
from interactive_editor import InteractiveCanvas
try:
    import slicer as _slicer_mod
    SLICER_AVAILABLE = True
except Exception:
    SLICER_AVAILABLE = False
from panel_decomposition import (
    decompose_box, decompose_l_shape, decompose_channel,
    panels_to_entities, panels_to_dxf,
)
try:
    import vectorizer as _vectorizer_mod
    VECTORIZER_AVAILABLE = True
except Exception:
    VECTORIZER_AVAILABLE = False

try:
    import warnings
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    warnings.filterwarnings('ignore', category=UserWarning, module='matplotlib')
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

try:
    import cv2
    import numpy as np
    from PIL import Image, ImageTk
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

OUTPUT_DIR = os.path.join('output', 'gui')
os.makedirs(OUTPUT_DIR, exist_ok=True)
TEMPLATE_STORAGE_FILE = os.path.join(OUTPUT_DIR, 'templates.json')
PROJECT_STORAGE_DIR = os.path.join(OUTPUT_DIR, 'projects')
os.makedirs(PROJECT_STORAGE_DIR, exist_ok=True)
PROJECTS_DIR = PROJECT_STORAGE_DIR  # Alias for backward compatibility

# Default values used in live preview and fabrication analysis when fields are blank
_PREVIEW_DEFAULTS = {
    'width': '100',
    'height': '50',
    'base_width': '80',
    'base_depth': '40',
    'wall_height': '20',
    'leg_height': '30',
    'bend_top': '0',
    'bend_bottom': '0',
    'bend_left': '0',
    'bend_right': '0',
    'pattern_size': '10',
    'spacing_x': '20',
    'spacing_y': '20',
    'inner_margin': '5',
}

FLANGE_FIELDS = [
    ('Top flange (mm)', 'bend_top'),
    ('Bottom flange (mm)', 'bend_bottom'),
    ('Left flange (mm)', 'bend_left'),
    ('Right flange (mm)', 'bend_right')
]

PATTERN_FIELDS = [
    ('Pattern Size (mm)', 'pattern_size'),
    ('Spacing X (mm)', 'spacing_x'),
    ('Spacing Y (mm)', 'spacing_y'),
    ('Inner Margin (mm)', 'inner_margin')
]


# ── Template registry ─────────────────────────────────────────────────────────
#
# Each entry describes one template the user can select.
# 'fields'  : ordered list of (label, param_key) for form rendering.
#
# DXF file generation is handled by _generate_dxf_file() so the lambdas are
# gone; entity generation for preview/analysis goes through preview_engine.

TEMPLATES: Dict[str, Dict] = {
    'Rectangle': {
        'fields': [
            ('Width (mm)',  'width'),
            ('Height (mm)', 'height'),
        ],
    },
    'Box Flat Pattern': {
        'fields': [
            ('Base Width (mm)',  'base_width'),
            ('Base Depth (mm)',  'base_depth'),
            ('Wall Height (mm)', 'wall_height'),
        ],
    },
    'L Bracket Flat Pattern': {
        'fields': [
            ('Base Width (mm)', 'base_width'),
            ('Base Depth (mm)', 'base_depth'),
            ('Leg Height (mm)', 'leg_height'),
        ],
    },
    'Channel Flat Pattern': {
        'fields': [
            ('Base Width (mm)',  'base_width'),
            ('Base Depth (mm)',  'base_depth'),
            ('Wall Height (mm)', 'wall_height'),
        ],
    },
}


def _generate_dxf_file(template_name: str, params: Dict, output_path: str) -> None:
    """
    Generate and save a DXF file for the given template + params.

    All float coercion happens here — callers pass raw string param dicts.
    Raises on invalid params or generation failure.
    """
    from dxf_generator import DXFGenerator

    gen = DXFGenerator(NoToolCompensation())

    if template_name == 'Rectangle':
        pattern_params = None
        if params.get('pattern_enabled'):
            pattern_params = {
                'enabled':      True,
                'pattern_type': params.get('pattern_type', 'circles'),
                'pattern_size': float(params.get('pattern_size', 10)),
                'spacing_x':    float(params.get('spacing_x', 20)),
                'spacing_y':    float(params.get('spacing_y', 20)),
                'inner_margin': float(params.get('inner_margin', 5)),
            }
        shape_params = {
            'width':       float(params['width']),
            'height':      float(params['height']),
            'bend_top':    float(params.get('bend_top', 0)),
            'bend_bottom': float(params.get('bend_bottom', 0)),
            'bend_left':   float(params.get('bend_left', 0)),
            'bend_right':  float(params.get('bend_right', 0)),
        }
        gen.generate_dxf('rectangle', shape_params, NoHoles(0),
                         output_path, pattern_params)

    elif template_name == 'Box Flat Pattern':
        create_box_flat_pattern_dxf(
            float(params['base_width']),
            float(params['base_depth']),
            float(params['wall_height']),
            filename=output_path,
            bend_top=float(params.get('bend_top', 0)),
            bend_bottom=float(params.get('bend_bottom', 0)),
            bend_left=float(params.get('bend_left', 0)),
            bend_right=float(params.get('bend_right', 0)),
            relief_type=params.get('relief_type', 'none'),
            relief_size=float(params.get('relief_size', 3.0)),
        )

    elif template_name == 'L Bracket Flat Pattern':
        create_l_bracket_flat_pattern_dxf(
            float(params['base_width']),
            float(params['base_depth']),
            float(params['leg_height']),
            filename=output_path,
            bend_top=float(params.get('bend_top', 0)),
            bend_bottom=float(params.get('bend_bottom', 0)),
            bend_left=float(params.get('bend_left', 0)),
            bend_right=float(params.get('bend_right', 0)),
            relief_type=params.get('relief_type', 'none'),
            relief_size=float(params.get('relief_size', 3.0)),
        )

    elif template_name == 'Channel Flat Pattern':
        create_channel_flat_pattern_dxf(
            float(params['base_width']),
            float(params['base_depth']),
            float(params['wall_height']),
            filename=output_path,
            bend_top=float(params.get('bend_top', 0)),
            bend_bottom=float(params.get('bend_bottom', 0)),
            bend_left=float(params.get('bend_left', 0)),
            bend_right=float(params.get('bend_right', 0)),
            relief_type=params.get('relief_type', 'none'),
            relief_size=float(params.get('relief_size', 3.0)),
        )

    else:
        raise ValueError(f"Unknown template: {template_name!r}")



# ── Design tokens ────────────────────────────────────────────────────────────
_CLR_ACCENT  = '#1565c0'   # primary blue
_CLR_ACCENT2 = '#1976d2'   # lighter blue (hover / selection)
_CLR_BG      = '#f5f6f8'   # window background
_CLR_PANEL   = '#ffffff'   # panel / card background
_CLR_BORDER  = '#dde1e7'   # separator / border
_CLR_SUCCESS = '#2e7d32'
_CLR_WARN    = '#e65100'
_CLR_ERROR   = '#b71c1c'
_CLR_MUTED   = '#6c757d'   # secondary text
_FONT_UI     = ('Segoe UI', 9)
_FONT_BOLD   = ('Segoe UI', 9, 'bold')
_FONT_TITLE  = ('Segoe UI', 13, 'bold')
_FONT_MONO   = ('Consolas', 8)


class CNCGeneratorGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('CNC DXF Generator  —  ALCUBOND Fabrication')
        self.geometry('1300x800')
        self.minsize(900, 620)
        self.resizable(True, True)
        self.configure(bg=_CLR_BG)
        self._apply_styles()

        # Template generation variables
        self.template_var = tk.StringVar(value='Rectangle')
        self.field_vars = {}
        self.flange_enabled = tk.BooleanVar(value=False)
        self.pattern_enabled = tk.BooleanVar(value=False)
        self.pattern_type_var = tk.StringVar(value='circles')
        self.last_output_path = None
        self.entry_widgets = []  # Track entry widgets for keyboard navigation
        self.preview_after_id = None  # For debouncing live preview updates
        self.relief_type_var = tk.StringVar(value='none')
        self.relief_size_var = tk.StringVar(value='3.0')

        # Scroll canvas registry — used by root mousewheel handler
        self._scroll_canvas_set: set = set()

        # Material optimization variables
        self.nesting_template_var = tk.StringVar(value='Rectangle')
        self.nesting_field_vars = {}
        self.sheet_width_var = tk.StringVar(value='1000')
        self.sheet_height_var = tk.StringVar(value='600')
        self.part_count_var = tk.StringVar(value='10')
        self.nesting_results = None

        # Fabrication advisor variables
        self.tool_diameter_var = tk.StringVar(value='6.0')
        self.fabrication_issues = []

        # Template preset storage
        self.templates = self.load_templates()

        # Project management variables
        self.current_project = None
        self.current_part_index = None
        self.project_parts = []  # List of part dictionaries

        # Interactive editor — shared entity list
        self._editor_entities: List[Dict] = []

        # Photo-to-DXF variables
        self.photo_image = None  # PIL Image object
        self.photo_cv_image = None  # OpenCV image
        self.photo_edges = None  # Edge detection result
        self.photo_contours = None  # Detected contours
        self.photo_simplified = None  # Simplified geometry
        self.photo_preview_mode = tk.StringVar(value='original')  # 'original', 'edges', 'contours'
        self.photo_threshold1_var = tk.StringVar(value='100')
        self.photo_threshold2_var = tk.StringVar(value='200')
        self.photo_min_contour_var = tk.StringVar(value='50')
        self.photo_smoothing_var = tk.StringVar(value='0.01')
        self.photo_scale_var = tk.StringVar(value='1.0')
        self.photo_target_width_var = tk.StringVar(value='')
        self.photo_target_height_var = tk.StringVar(value='')

        # Smart geometry recognition options
        self.photo_smart_geom_enabled = tk.BooleanVar(value=False)
        self.photo_detect_lines = tk.BooleanVar(value=True)
        self.photo_detect_circles = tk.BooleanVar(value=True)
        self.photo_detect_rectangles = tk.BooleanVar(value=True)
        self.photo_merge_collinear = tk.BooleanVar(value=True)
        self.photo_remove_tiny = tk.BooleanVar(value=True)

        self.create_widgets()
        # Initialize fields after widgets are created
        self.render_fields()
        self.render_nesting_fields()
        self.update_live_preview()  # Initial preview

    # ── Theming ───────────────────────────────────────────────────────────────
    def _apply_styles(self):
        """Apply clam theme and custom ttk styles."""
        style = ttk.Style(self)
        style.theme_use('clam')

        # Base element styles
        style.configure('.',
            background=_CLR_BG,
            foreground='#1a1a2e',
            font=_FONT_UI,
            relief='flat',
        )

        # Notebook (tabs)
        style.configure('TNotebook', background=_CLR_BG, tabmargins=[0, 0, 0, 0])
        style.configure('TNotebook.Tab',
            background='#dde1e7',
            foreground='#444',
            padding=[14, 6],
            font=_FONT_UI,
        )
        style.map('TNotebook.Tab',
            background=[('selected', _CLR_ACCENT), ('active', _CLR_ACCENT2)],
            foreground=[('selected', 'white'),      ('active', 'white')],
        )

        # Frames
        style.configure('TFrame', bg=_CLR_PANEL, relief='flat', bd=1, highlightthickness=1, highlightbackground=_CLR_BORDER, font=_FONT_UI)
        style.configure('Card.TFrame', background=_CLR_PANEL, relief='flat')

        # LabelFrames — card-like appearance
        style.configure('TLabelframe', background=_CLR_PANEL, relief='flat', borderwidth=1,
                        bordercolor=_CLR_BORDER)
        style.configure('TLabelframe.Label', background=_CLR_PANEL,
                        foreground=_CLR_ACCENT, font=_FONT_BOLD)

        # Labels
        style.configure('TLabel', background=_CLR_PANEL, foreground='#1a1a2e', font=_FONT_UI)
        style.configure('Muted.TLabel', foreground=_CLR_MUTED)

        # Buttons — primary
        style.configure('TButton',
            background=_CLR_ACCENT,
            foreground='white',
            font=_FONT_BOLD,
            padding=[10, 5],
            relief='flat',
            borderwidth=0,
        )
        style.map('TButton',
            background=[('active', _CLR_ACCENT2), ('pressed', '#0d47a1')],
            relief=[('active', 'flat')],
        )

        # Secondary button (outline-ish)
        style.configure('Secondary.TButton',
            background='#e8eaf0',
            foreground=_CLR_ACCENT,
            font=_FONT_UI,
            padding=[8, 4],
            relief='flat',
        )
        style.map('Secondary.TButton',
            background=[('active', '#d0d5e8'), ('pressed', '#bcc3de')],
        )

        # Danger button
        style.configure('Danger.TButton',
            background='#c62828',
            foreground='white',
            font=_FONT_UI,
            padding=[8, 4],
            relief='flat',
        )
        style.map('Danger.TButton',
            background=[('active', '#b71c1c')],
        )

        # Entries
        style.configure('TEntry',
            fieldbackground=_CLR_PANEL,
            foreground='#1a1a2e',
            insertcolor='#1a1a2e',
            relief='flat',
            borderwidth=1,
            padding=[4, 3],
        )
        style.map('TEntry', bordercolor=[('focus', _CLR_ACCENT), ('!focus', _CLR_BORDER)])

        # OptionMenu
        style.configure('TMenubutton',
            background=_CLR_PANEL,
            foreground='#1a1a2e',
            relief='flat',
            borderwidth=1,
            padding=[4, 3],
        )
        style.map('TMenubutton', background=[('active', '#e8eaf0')])

        # Checkbuttons
        style.configure('TCheckbutton', background=_CLR_BG, foreground='#1a1a2e', font=_FONT_UI)
        style.map('TCheckbutton', background=[('active', _CLR_BG)])

        # Radiobuttons
        style.configure('TRadiobutton', background=_CLR_BG, foreground='#1a1a2e', font=_FONT_UI)
        style.map('TRadiobutton', background=[('active', _CLR_BG)])

        # Scrollbars — thin and subtle
        style.configure('TScrollbar',
            background=_CLR_BORDER,
            troughcolor=_CLR_BG,
            relief='flat',
            arrowsize=12,
            width=10,
        )
        style.map('TScrollbar', background=[('active', '#b0b8c4')])

        # Separator
        style.configure('TSeparator', background=_CLR_BORDER)

        # Listbox-wrapping frame
        style.configure('Inset.TFrame', background=_CLR_PANEL, relief='flat')

        # Status bar label
        style.configure('Status.TLabel',
            background='#e8eaf0',
            foreground=_CLR_MUTED,
            font=_FONT_UI,
            padding=[8, 3],
        )
        style.configure('StatusOk.TLabel',
            background='#e8eaf0',
            foreground=_CLR_SUCCESS,
            font=_FONT_UI,
            padding=[8, 3],
        )
        style.configure('StatusErr.TLabel',
            background='#e8eaf0',
            foreground=_CLR_ERROR,
            font=_FONT_UI,
            padding=[8, 3],
        )

        # Header bar label
        style.configure('Header.TFrame', background=_CLR_ACCENT)
        style.configure('Header.TLabel',
            background=_CLR_ACCENT,
            foreground='white',
            font=_FONT_TITLE,
            padding=[16, 10],
        )
        style.configure('HeaderSub.TLabel',
            background=_CLR_ACCENT,
            foreground='#bbdefb',
            font=_FONT_UI,
            padding=[16, 0],
        )

    def on_field_change(self, *args):
        """Callback for field value changes."""
        self.schedule_preview_update()

    def on_parse_description(self):
        """Parse the natural-language part description and update GUI fields."""
        description = self.description_text.get('1.0', tk.END).strip()
        if not description:
            messagebox.showinfo('Describe Part', 'Please enter a part description first.')
            return

        parsed = self.parse_part_description(description)
        self.apply_parsed_description(parsed)

    def parse_part_description(self, description):
        """Convert a natural language description into template and parameter values."""
        text = description.lower()
        parsed = {
            'template': self.choose_template_from_description(text),
            'params': {},
            'pattern_enabled': False,
            'pattern_type': 'circles',
            'flange_values': {},
            'flange_enabled': False
        }

        parsed['params'].update(self.extract_dimension_params(text, parsed['template']))
        flange_values = self.extract_flange_params(text)
        parsed['flange_values'] = flange_values
        parsed['flange_enabled'] = bool(flange_values)

        pattern_params = self.extract_pattern_params(text)
        if pattern_params:
            parsed['pattern_enabled'] = True
            parsed['pattern_type'] = pattern_params.get('pattern_type', 'circles')
            parsed['params'].update(pattern_params)

        return parsed

    def apply_parsed_description(self, parsed):
        """Apply parsed description values to the GUI fields and update the preview."""
        self.template_var.set(parsed.get('template', self.template_var.get()))
        self.flange_enabled.set(parsed.get('flange_enabled', False))
        self.pattern_enabled.set(parsed.get('pattern_enabled', False))
        self.pattern_type_var.set(parsed.get('pattern_type', 'circles'))

        self.render_fields()

        for name, value in parsed.get('params', {}).items():
            if name in self.field_vars:
                self.field_vars[name].set(str(value))

        for name, value in parsed.get('flange_values', {}).items():
            if name in self.field_vars:
                self.field_vars[name].set(str(value))

        if parsed.get('pattern_enabled', False):
            self.pattern_type_var.set(parsed.get('pattern_type', 'circles'))

        self.schedule_preview_update()

    def load_templates(self):
        """Load saved templates from local JSON storage."""
        try:
            if os.path.exists(TEMPLATE_STORAGE_FILE):
                with open(TEMPLATE_STORAGE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_templates(self):
        """Persist saved templates to local JSON storage."""
        try:
            with open(TEMPLATE_STORAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.templates, f, indent=2)
        except Exception as exc:
            messagebox.showerror('Save Template', f'Failed to save templates: {exc}')

    def refresh_template_listbox(self):
        """Refresh the template list display."""
        if not hasattr(self, 'templates_listbox'):
            return
        self.templates_listbox.delete(0, tk.END)
        for name in sorted(self.templates.keys()):
            self.templates_listbox.insert(tk.END, name)

    def get_current_template_state(self):
        """Get the current GUI template state for saving."""
        params = {}
        for name, var in self.field_vars.items():
            params[name] = var.get().strip()

        return {
            'template': self.template_var.get(),
            'params': params,
            'flange_enabled': self.flange_enabled.get(),
            'pattern_enabled': self.pattern_enabled.get(),
            'pattern_type': self.pattern_type_var.get(),
            'tool_diameter': self.tool_diameter_var.get(),
            'relief_type': self.relief_type_var.get(),
            'relief_size': self.relief_size_var.get(),
        }

    def apply_template_state(self, state):
        """Apply a template state to the GUI and refresh preview."""
        self.template_var.set(state.get('template', self.template_var.get()))
        self.flange_enabled.set(state.get('flange_enabled', False))
        self.pattern_enabled.set(state.get('pattern_enabled', False))
        self.pattern_type_var.set(state.get('pattern_type', 'circles'))
        self.relief_type_var.set(state.get('relief_type', 'none'))
        self.relief_size_var.set(state.get('relief_size', '3.0'))

        self.render_fields()

        for name, value in state.get('params', {}).items():
            if name in self.field_vars:
                self.field_vars[name].set(str(value))

        self.tool_diameter_var.set(state.get('tool_diameter', self.tool_diameter_var.get()))
        self.schedule_preview_update()

    def save_template(self):
        """Save the current GUI state as a named template."""
        name = simpledialog.askstring('Save Template', 'Enter a name for this template:')
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if name in self.templates:
            if not messagebox.askyesno('Save Template', f'Template "{name}" already exists. Overwrite?'):
                return

        self.templates[name] = self.get_current_template_state()
        self.save_templates()
        self.refresh_template_listbox()
        messagebox.showinfo('Save Template', f'Template "{name}" saved.')

    def load_template(self):
        """Load the selected saved template into the GUI."""
        selection = self.templates_listbox.curselection()
        if not selection:
            messagebox.showinfo('Load Template', 'Please select a template to load.')
            return
        name = self.templates_listbox.get(selection[0])
        state = self.templates.get(name)
        if not state:
            messagebox.showerror('Load Template', 'Selected template not found.')
            return
        self.apply_template_state(state)
        messagebox.showinfo('Load Template', f'Template "{name}" loaded.')

    def choose_template_from_description(self, text):
        """Choose the best matching template from the user description."""
        scores = {
            'Rectangle': 0,
            'Box Flat Pattern': 0,
            'L Bracket Flat Pattern': 0,
            'Channel Flat Pattern': 0
        }

        if 'l bracket' in text or 'l-bracket' in text or 'bracket' in text:
            scores['L Bracket Flat Pattern'] += 3
        if 'channel' in text or 'c channel' in text:
            scores['Channel Flat Pattern'] += 3
        if 'box' in text or 'flat pattern' in text and 'base' in text:
            scores['Box Flat Pattern'] += 2
        if 'rectangle' in text or 'rectangular' in text:
            scores['Rectangle'] += 2
        if 'wall height' in text or 'base width' in text or 'base depth' in text:
            scores['Box Flat Pattern'] += 1
            scores['Channel Flat Pattern'] += 1
        if 'leg height' in text or 'l bracket' in text:
            scores['L Bracket Flat Pattern'] += 2
        if 'bend' in text or 'flange' in text:
            scores['Box Flat Pattern'] += 1
            scores['L Bracket Flat Pattern'] += 1
            scores['Channel Flat Pattern'] += 1

        best = max(scores, key=lambda key: scores[key])
        if scores[best] == 0:
            return self.template_var.get()
        return best

    def extract_dimension_params(self, text, template):
        """Extract dimension fields from the description text."""
        params = {}

        def find_number(pattern):
            match = re.search(pattern, text)
            return match.group(1) if match else None

        patterns = [
            (r'base width(?: is|:)?\s*(\d+(?:\.\d+)?)', 'base_width'),
            (r'base depth(?: is|:)?\s*(\d+(?:\.\d+)?)', 'base_depth'),
            (r'wall height(?: is|:)?\s*(\d+(?:\.\d+)?)', 'wall_height'),
            (r'leg height(?: is|:)?\s*(\d+(?:\.\d+)?)', 'leg_height'),
            (r'width(?: is|:)?\s*(\d+(?:\.\d+)?)', 'width'),
            (r'height(?: is|:)?\s*(\d+(?:\.\d+)?)', 'height'),
            (r'depth(?: is|:)?\s*(\d+(?:\.\d+)?)', 'base_depth')
        ]

        for pattern, name in patterns:
            value = find_number(pattern)
            if value:
                params[name] = value

        if template == 'Rectangle':
            if 'width' not in params or 'height' not in params:
                pair = re.search(r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)', text)
                if pair:
                    params.setdefault('width', pair.group(1))
                    params.setdefault('height', pair.group(2))
        else:
            if 'base_width' not in params or 'base_depth' not in params:
                pair = re.search(r'(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)', text)
                if pair:
                    params.setdefault('base_width', pair.group(1))
                    params.setdefault('base_depth', pair.group(2))

            if template == 'L Bracket Flat Pattern' and 'leg_height' not in params:
                leg_match = find_number(r'leg height(?: is|:)?\s*(\d+(?:\.\d+)?)')
                if leg_match:
                    params['leg_height'] = leg_match
            if template in ['Box Flat Pattern', 'Channel Flat Pattern'] and 'wall_height' not in params:
                wall_match = find_number(r'wall height(?: is|:)?\s*(\d+(?:\.\d+)?)')
                if wall_match:
                    params['wall_height'] = wall_match

        if template == 'Box Flat Pattern' and 'wall_height' not in params and 'leg_height' in params:
            params['wall_height'] = params['leg_height']

        if template == 'Channel Flat Pattern' and 'wall_height' not in params:
            params['wall_height'] = find_number(r'wall height(?: is|:)?\s*(\d+(?:\.\d+)?)')

        # Fallback to plain numbers if needed
        if template == 'Rectangle' and ('width' not in params or 'height' not in params):
            numbers = re.findall(r'(\d+(?:\.\d+)?)\s*mm', text)
            if len(numbers) >= 2:
                params.setdefault('width', numbers[0])
                params.setdefault('height', numbers[1])
        elif template in ['Box Flat Pattern', 'Channel Flat Pattern', 'L Bracket Flat Pattern']:
            numbers = re.findall(r'(\d+(?:\.\d+)?)\s*mm', text)
            if len(numbers) >= 2:
                params.setdefault('base_width', numbers[0])
                params.setdefault('base_depth', numbers[1])
            if template != 'Rectangle' and len(numbers) >= 3:
                if template == 'L Bracket Flat Pattern':
                    params.setdefault('leg_height', numbers[2])
                else:
                    params.setdefault('wall_height', numbers[2])

        return params

    def extract_flange_params(self, text):
        """Extract flange and bend values from description text."""
        flange = {}
        sides = ['top', 'bottom', 'left', 'right']
        for side in sides:
            match = re.search(rf'{side} (?:flange|bend)(?: is|:)?\s*(\d+(?:\.\d+)?)', text)
            if not match:
                match = re.search(rf'(\d+(?:\.\d+)?)(?:\s*mm)?\s*{side} (?:flange|bend)', text)
            if match:
                flange[f'bend_{side}'] = match.group(1)

        if not flange:
            generic = re.search(r'(?:flange|bend)(?: size| amount| value)?(?: is|:)?\s*(\d+(?:\.\d+)?)', text)
            if generic:
                for side in sides:
                    flange[f'bend_{side}'] = generic.group(1)

        return flange

    def extract_pattern_params(self, text):
        """Extract pattern type and spacing values from the description text."""
        if not re.search(r'pattern|hole|slot|grid', text):
            return {}

        params = {}
        params['pattern_type'] = 'circles'
        if 'slot' in text or 'slots' in text:
            params['pattern_type'] = 'slots'
        elif 'rectangle' in text and 'pattern' in text:
            params['pattern_type'] = 'rectangles'

        size_match = re.search(r'(?:pattern size|hole size|circle diameter|diameter|radius|slot width|slot length)(?: is|:)?\s*(\d+(?:\.\d+)?)', text)
        if size_match:
            params['pattern_size'] = size_match.group(1)
        else:
            hole_size = re.search(r'(\d+(?:\.\d+)?)(?:\s*mm)?\s*(?:hole|slot|circle|diameter)', text)
            if hole_size:
                params['pattern_size'] = hole_size.group(1)

        spacing = re.findall(r'(\d+(?:\.\d+)?)(?:\s*mm)?\s*(?:spacing|pitch)', text)
        if not spacing:
            spacing = re.findall(r'(?:spacing|pitch)(?: of)?(?: is|:)?\s*(\d+(?:\.\d+)?)(?:\s*mm)?', text)
        if spacing:
            params['spacing_x'] = spacing[0]
            params['spacing_y'] = spacing[0]
            if len(spacing) > 1:
                params['spacing_y'] = spacing[1]

        inner_margin_match = re.search(r'(?:inner margin|margin)(?: is|:)?\s*(\d+(?:\.\d+)?)', text)
        if inner_margin_match:
            params['inner_margin'] = inner_margin_match.group(1)

        return params

    def create_widgets(self):
        # ── Header bar ────────────────────────────────────────────────────────
        header = ttk.Frame(self, style='Header.TFrame')
        header.pack(fill='x', side='top')
        ttk.Label(header, text='CNC DXF Generator', style='Header.TLabel').pack(side='left')
        ttk.Label(header, text='ALCUBOND Fabrication System', style='HeaderSub.TLabel').pack(side='left', pady=(4, 0))

        # ── Bottom status bar ─────────────────────────────────────────────────
        status_bar = ttk.Frame(self, style='Header.TFrame')
        status_bar.configure(style='TFrame')
        status_bar['relief'] = 'flat'
        status_sep = ttk.Separator(self, orient='horizontal')
        status_sep.pack(fill='x', side='bottom')
        status_container = ttk.Frame(self)
        status_container.pack(fill='x', side='bottom')
        status_container.configure(style='TFrame')
        self.status_label = ttk.Label(status_container, text='Ready',
                                      style='StatusOk.TLabel', anchor='w')
        self.status_label.pack(side='left', fill='x', expand=True)
        ttk.Label(status_container, text=f'Output: {OUTPUT_DIR}',
                  style='Status.TLabel', anchor='e').pack(side='right')

        # ── Notebook (tabs) ───────────────────────────────────────────────────
        self.tab_control = ttk.Notebook(self)

        # Tab 1: DXF Generator
        self.dxf_tab = ttk.Frame(self.tab_control, style='TFrame')
        self.tab_control.add(self.dxf_tab, text='  DXF Generator  ')
        self.create_dxf_generator_tab()

        # Tab 2: Project Management
        self.project_tab = ttk.Frame(self.tab_control, style='TFrame')
        self.tab_control.add(self.project_tab, text='  Project Management  ')
        self.create_project_tab()

        # Tab 3: Material Optimization
        self.nesting_tab = ttk.Frame(self.tab_control, style='TFrame')
        self.tab_control.add(self.nesting_tab, text='  Material Optimization  ')
        self.create_nesting_tab()

        # Tab 4: Photo-to-DXF
        self.photo_tab = ttk.Frame(self.tab_control, style='TFrame')
        self.tab_control.add(self.photo_tab, text='  Photo-to-DXF  ')
        self.create_photo_to_dxf_tab()

        # Tab 5: Interactive Editor
        self.editor_tab = ttk.Frame(self.tab_control, style='TFrame')
        self.tab_control.add(self.editor_tab, text='  Interactive Editor  ')
        self.create_interactive_editor_tab()

        # Tab 6: 3D Decompose
        self.decompose_tab = ttk.Frame(self.tab_control, style='TFrame')
        self.tab_control.add(self.decompose_tab, text='  3D → Panels  ')
        self.create_3d_decompose_tab()

        # Tab 7: Stacked Slicer
        self.slicer_tab = ttk.Frame(self.tab_control, style='TFrame')
        self.tab_control.add(self.slicer_tab, text='  Stacked Slicer  ')
        self.create_slicer_tab()

        self.tab_control.pack(expand=1, fill='both', padx=0, pady=0)

        # Single root-level mousewheel handler — routes to whichever registered
        # scroll canvas is under the cursor at the time of the event.
        self.bind('<MouseWheel>', self._on_root_mousewheel)
        self.bind('<Button-4>', self._on_root_linux_scroll)
        self.bind('<Button-5>', self._on_root_linux_scroll)

    def create_dxf_generator_tab(self):
        """Create the DXF Generator tab — left controls pane + right preview pane."""
        outer = ttk.Frame(self.dxf_tab)
        outer.pack(fill='both', expand=True)

        # ── Left pane: scrollable controls (fixed ~380px wide) ──────────────
        left_border = ttk.Frame(outer, width=1, style='TFrame')
        left_border.pack(side='left', fill='y')

        left_outer = ttk.Frame(outer, width=380)
        left_outer.pack(side='left', fill='y')
        left_outer.pack_propagate(False)

        self.dxf_canvas = tk.Canvas(left_outer, highlightthickness=0,
                                    background=_CLR_BG, bd=0)
        self.dxf_canvas.pack(side='left', fill='both', expand=True)

        self.dxf_scrollbar = ttk.Scrollbar(left_outer, orient='vertical',
                                           command=self.dxf_canvas.yview)
        self.dxf_scrollbar.pack(side='right', fill='y')
        self.dxf_canvas.configure(yscrollcommand=self.dxf_scrollbar.set)
        self.dxf_canvas.bind('<Configure>', self._on_dxf_canvas_configure)

        self.dxf_scrollable_frame = ttk.Frame(self.dxf_canvas)
        self._left_window_id = self.dxf_canvas.create_window(
            (0, 0), window=self.dxf_scrollable_frame, anchor='nw')

        # Register for root mousewheel routing; also update scroll region when
        # inner frame grows (e.g. after showing flange / pattern sections).
        self._scroll_canvas_set.add(self.dxf_canvas)
        self.dxf_scrollable_frame.bind('<Configure>', self._on_dxf_inner_configure)

        main_frame = ttk.Frame(self.dxf_scrollable_frame, padding=(12, 10, 10, 10))
        main_frame.pack(fill='both', expand=True)
        main_frame.columnconfigure(0, weight=1)

        # ── Template selector ────────────────────────────────────────────────
        tpl_lf = ttk.LabelFrame(main_frame, text='Template', padding=(10, 8))
        tpl_lf.pack(fill='x', pady=(0, 8))
        tpl_lf.columnconfigure(0, weight=1)
        template_menu = ttk.OptionMenu(
            tpl_lf, self.template_var,
            self.template_var.get(), *TEMPLATES.keys(),
            command=self.on_template_change
        )
        template_menu.grid(row=0, column=0, sticky='ew')

        checks_row = ttk.Frame(tpl_lf)
        checks_row.grid(row=1, column=0, sticky='w', pady=(8, 0))
        self.flange_checkbox = ttk.Checkbutton(
            checks_row, text='Flanges / Bends',
            variable=self.flange_enabled, command=self.on_flange_toggle)
        self.flange_checkbox.pack(side='left', padx=(0, 16))
        self.pattern_checkbox = ttk.Checkbutton(
            checks_row, text='Cut Pattern',
            variable=self.pattern_enabled, command=self.on_pattern_toggle)
        self.pattern_checkbox.pack(side='left')

        # ── Tool diameter ────────────────────────────────────────────────────
        tool_lf = ttk.LabelFrame(main_frame, text='Tool', padding=(10, 8))
        tool_lf.pack(fill='x', pady=(0, 8))
        tool_lf.columnconfigure(1, weight=1)
        ttk.Label(tool_lf, text='Diameter (mm)').grid(row=0, column=0, sticky='w', padx=(0, 8))
        tool_entry = ttk.Entry(tool_lf, textvariable=self.tool_diameter_var)
        tool_entry.grid(row=0, column=1, sticky='ew')
        tool_entry.bind('<KeyRelease>', lambda e: self.schedule_preview_update())

        # ── Shape parameters (populated by render_fields) ────────────────────
        self.shape_frame = ttk.LabelFrame(main_frame, text='Shape Parameters', padding=(10, 8))
        self.shape_frame.pack(fill='x', pady=(0, 8))
        self.shape_frame.columnconfigure((0, 2), weight=1)

        # ── Flange section ───────────────────────────────────────────────────
        self.flange_frame = ttk.LabelFrame(main_frame, text='Flange / Bends', padding=(10, 8))
        self.flange_section_frame = self.flange_frame
        self.flange_section_frame.columnconfigure((0, 2), weight=1)

        # ── Pattern section ──────────────────────────────────────────────────
        self.pattern_frame = ttk.LabelFrame(main_frame, text='Cut Pattern', padding=(10, 8))
        self.pattern_section_frame = self.pattern_frame
        self.pattern_section_frame.columnconfigure((0, 2), weight=1)

        # ── Corner relief ────────────────────────────────────────────────────
        self.relief_frame = ttk.LabelFrame(main_frame, text='Corner Relief', padding=(10, 8))
        self.relief_frame.columnconfigure(1, weight=1)
        self.relief_frame.columnconfigure(3, weight=1)
        ttk.Label(self.relief_frame, text='Type').grid(row=0, column=0, sticky='w', padx=(0, 6))
        relief_menu = ttk.OptionMenu(
            self.relief_frame, self.relief_type_var,
            self.relief_type_var.get(), 'none', 'square', 'round', 'v_cut',
            command=lambda _: self.schedule_preview_update()
        )
        relief_menu.grid(row=0, column=1, sticky='ew')
        ttk.Label(self.relief_frame, text='Size (mm)').grid(row=0, column=2, sticky='w', padx=(12, 6))
        relief_size_entry = ttk.Entry(self.relief_frame, textvariable=self.relief_size_var)
        relief_size_entry.grid(row=0, column=3, sticky='ew')
        relief_size_entry.bind('<KeyRelease>', lambda e: self.schedule_preview_update())
        self.relief_type_var.trace_add('write', lambda *_: self.schedule_preview_update())
        self.relief_size_var.trace_add('write', lambda *_: self.schedule_preview_update())

        # ── Saved templates ──────────────────────────────────────────────────
        presets_lf = ttk.LabelFrame(main_frame, text='Saved Templates', padding=(10, 8))
        presets_lf.pack(fill='x', pady=(0, 8))
        presets_lf.columnconfigure(0, weight=1)

        lb_frame = ttk.Frame(presets_lf)
        lb_frame.grid(row=0, column=0, columnspan=2, sticky='nsew')
        lb_frame.columnconfigure(0, weight=1)
        self.templates_listbox = tk.Listbox(
            lb_frame, height=4, exportselection=False,
            font=_FONT_UI, bg=_CLR_PANEL, relief='flat',
            selectbackground=_CLR_ACCENT, selectforeground='white',
            bd=1, highlightthickness=0)
        self.templates_listbox.grid(row=0, column=0, sticky='nsew')
        presets_sb = ttk.Scrollbar(lb_frame, orient='vertical',
                                   command=self.templates_listbox.yview)
        presets_sb.grid(row=0, column=1, sticky='ns')
        self.templates_listbox.config(yscrollcommand=presets_sb.set)

        pb = ttk.Frame(presets_lf)
        pb.grid(row=1, column=0, columnspan=2, pady=(6, 0), sticky='ew')
        pb.columnconfigure((0, 1), weight=1)
        self.save_template_button = ttk.Button(pb, text='Save', style='Secondary.TButton',
                                               command=self.save_template)
        self.save_template_button.grid(row=0, column=0, sticky='ew', padx=(0, 4))
        self.load_template_button = ttk.Button(pb, text='Load', style='Secondary.TButton',
                                               command=self.load_template)
        self.load_template_button.grid(row=0, column=1, sticky='ew', padx=(4, 0))
        self.refresh_template_listbox()

        # ── Describe part (NL parser) ────────────────────────────────────────
        desc_lf = ttk.LabelFrame(main_frame, text='Describe Part (Natural Language)', padding=(10, 8))
        desc_lf.pack(fill='x', pady=(0, 8))
        self.description_text = tk.Text(
            desc_lf, height=3, wrap='word',
            font=_FONT_UI, bg=_CLR_PANEL, relief='flat',
            bd=1, highlightthickness=1, highlightbackground=_CLR_BORDER,
            highlightcolor=_CLR_ACCENT)
        self.description_text.pack(fill='x', pady=(0, 6))
        ttk.Button(desc_lf, text='Parse Description', style='Secondary.TButton',
                   command=self.on_parse_description).pack(anchor='e')

        # ── Generate / Open buttons ──────────────────────────────────────────
        btn_row = ttk.Frame(main_frame)
        btn_row.pack(fill='x', pady=(4, 8))
        btn_row.columnconfigure(0, weight=1)
        self.generate_button = ttk.Button(btn_row, text='Generate DXF',
                                          command=self.on_generate)
        self.generate_button.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        self.open_button = ttk.Button(btn_row, text='Open Output Folder',
                                      style='Secondary.TButton',
                                      command=self.open_output_folder)
        self.open_button.grid(row=1, column=0, sticky='ew', pady=(0, 4))
        self.send_to_editor_button = ttk.Button(
            btn_row, text='Send to Editor ›',
            style='Secondary.TButton',
            command=self.on_send_to_editor,
        )
        self.send_to_editor_button.grid(row=2, column=0, sticky='ew')

        # ── Right pane: preview + advisor ─────────────────────────────────────
        ttk.Separator(outer, orient='vertical').pack(side='left', fill='y')

        right_pane = ttk.Frame(outer, padding=(10, 10, 12, 10))
        right_pane.pack(side='left', fill='both', expand=True)
        right_pane.rowconfigure(0, weight=3)
        right_pane.rowconfigure(2, weight=1)
        right_pane.columnconfigure(0, weight=1)

        # Live preview canvas
        self.preview_frame = ttk.LabelFrame(right_pane, text='Live Preview', padding=6)
        self.preview_frame.grid(row=0, column=0, sticky='nsew', pady=(0, 6))

        if MATPLOTLIB_AVAILABLE:
            self.preview_fig = Figure(figsize=(7, 5), dpi=100,
                                      facecolor=_CLR_PANEL)
            self.preview_fig.subplots_adjust(left=0.10, right=0.97, top=0.93, bottom=0.09)
            self.preview_ax = self.preview_fig.add_subplot(111)
            self.preview_canvas = FigureCanvasTkAgg(self.preview_fig,
                                                    master=self.preview_frame)
            self.preview_canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            ttk.Label(self.preview_frame,
                      text='Install matplotlib for live preview',
                      style='Muted.TLabel').pack(pady=40)

        # Preview toolbar (Full Preview + metadata row)
        tb_row = ttk.Frame(right_pane)
        tb_row.grid(row=1, column=0, sticky='ew', pady=(0, 6))
        tb_row.columnconfigure(1, weight=1)
        self.preview_button = ttk.Button(tb_row, text='Full Preview…',
                                         style='Secondary.TButton',
                                         command=self.on_preview)
        self.preview_button.grid(row=0, column=0, sticky='w')
        self.metadata_text = tk.Text(
            tb_row, height=2, wrap='word', state='disabled',
            font=_FONT_MONO, bg='#eef0f4', relief='flat',
            bd=0, highlightthickness=0)
        self.metadata_text.grid(row=0, column=1, sticky='ew', padx=(10, 0))

        # Fabrication advisor
        self.advisor_frame = ttk.LabelFrame(right_pane,
                                            text='Smart Fabrication Advisor', padding=8)
        self.advisor_frame.grid(row=2, column=0, sticky='nsew')
        self.advisor_frame.rowconfigure(0, weight=1)
        self.advisor_frame.columnconfigure(0, weight=1)

        adv_inner = ttk.Frame(self.advisor_frame)
        adv_inner.grid(row=0, column=0, sticky='nsew')
        adv_inner.rowconfigure(0, weight=1)
        adv_inner.columnconfigure(0, weight=1)

        adv_sb = ttk.Scrollbar(adv_inner, orient='vertical')
        adv_sb.grid(row=0, column=1, sticky='ns')
        self.warnings_listbox = tk.Listbox(
            adv_inner, height=6, yscrollcommand=adv_sb.set,
            font=_FONT_UI, bg=_CLR_PANEL, relief='flat',
            selectbackground=_CLR_ACCENT, selectforeground='white',
            bd=0, highlightthickness=0)
        self.warnings_listbox.grid(row=0, column=0, sticky='nsew')
        adv_sb.config(command=self.warnings_listbox.yview)

        self.advisor_status_label = ttk.Label(self.advisor_frame,
                                              text='Ready to analyze',
                                              style='Muted.TLabel')
        self.advisor_status_label.grid(row=1, column=0, sticky='w', pady=(4, 0))

    # ── Interactive Editor tab ────────────────────────────────────────────────

    def create_interactive_editor_tab(self):
        """Interactive editor: select / move / delete / duplicate / rotate entities."""
        outer = ttk.Frame(self.editor_tab)
        outer.pack(fill='both', expand=True)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        # ── Toolbar row 1: edit actions ───────────────────────────────────────
        tb1 = ttk.Frame(outer, padding=(8, 4, 8, 0))
        tb1.grid(row=0, column=0, sticky='ew')

        def _btn(parent, text, cmd, style='Secondary.TButton', **kw):
            return ttk.Button(parent, text=text, command=cmd, style=style, **kw)

        _btn(tb1, 'Select All',     self._editor_select_all).pack(side='left', padx=(0, 3))
        _btn(tb1, 'Delete',         self._editor_delete_selected).pack(side='left', padx=(0, 3))
        _btn(tb1, 'Duplicate',      self._editor_duplicate).pack(side='left', padx=(0, 3))
        _btn(tb1, 'Rotate 90°',     self._editor_rotate_cw).pack(side='left', padx=(0, 3))
        _btn(tb1, 'Rotate -90°',    self._editor_rotate_ccw).pack(side='left', padx=(0, 3))
        ttk.Separator(tb1, orient='vertical').pack(side='left', fill='y', padx=(4, 4))
        _btn(tb1, '🔒 Lock',        self._editor_lock_selected).pack(side='left', padx=(0, 3))
        _btn(tb1, '🔓 Unlock All',  self._editor_unlock_all).pack(side='left', padx=(0, 3))
        ttk.Separator(tb1, orient='vertical').pack(side='left', fill='y', padx=(4, 4))
        self._editor_undo_btn = _btn(tb1, 'Undo', self._editor_undo)
        self._editor_undo_btn.pack(side='left', padx=(0, 3))
        self._editor_redo_btn = _btn(tb1, 'Redo', self._editor_redo)
        self._editor_redo_btn.pack(side='left', padx=(0, 3))
        ttk.Separator(tb1, orient='vertical').pack(side='left', fill='y', padx=(4, 4))
        _btn(tb1, 'Fit to View',   self._editor_fit).pack(side='left', padx=(0, 3))
        _btn(tb1, 'Clear',         self._editor_clear).pack(side='left', padx=(0, 3))
        ttk.Separator(tb1, orient='vertical').pack(side='left', fill='y', padx=(4, 4))
        _btn(tb1, 'Export DXF…',   self._editor_export_dxf, style='TButton').pack(side='left', padx=(0, 3))

        # ── Status / hint row ─────────────────────────────────────────────────
        tb2 = ttk.Frame(outer, padding=(8, 0, 8, 2))
        tb2.grid(row=1, column=0, sticky='ew')

        self._editor_sel_label = ttk.Label(tb2, text='0 selected  |  0 entities',
                                           style='Muted.TLabel')
        self._editor_sel_label.pack(side='left')

        hint = ttk.Label(
            tb2,
            text='LMB: select/drag  ·  Box drag: multi-select  ·  Arrows: nudge (Shift=10mm)  ·'
                 '  Ctrl+D: duplicate  ·  Ctrl+R: rotate  ·  Ctrl+Z/Y: undo/redo  ·  RMB: pan',
            style='Muted.TLabel',
        )
        hint.pack(side='right')

        # ── Canvas ────────────────────────────────────────────────────────────
        canvas_frame = ttk.Frame(outer, style='Card.TFrame')
        canvas_frame.grid(row=2, column=0, sticky='nsew', padx=8, pady=(2, 8))
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)  # canvas row expands

        self.interactive_canvas = InteractiveCanvas(
            canvas_frame,
            on_selection_change=self._editor_on_selection_change,
            on_modified=self._editor_on_modified,
        )
        self.interactive_canvas.widget.grid(row=0, column=0, sticky='nsew')

    def _editor_on_selection_change(self, count: int) -> None:
        total = self.interactive_canvas.entity_count
        self._editor_sel_label.config(
            text=f'{count} selected  |  {total} entities'
        )

    def _editor_on_modified(self) -> None:
        total = self.interactive_canvas.entity_count
        sel   = self.interactive_canvas.selection_count
        self._editor_sel_label.config(
            text=f'{sel} selected  |  {total} entities'
        )
        self._update_undo_buttons()

    def _editor_select_all(self) -> None:
        self.interactive_canvas.select_all()

    def _editor_delete_selected(self) -> None:
        self.interactive_canvas.delete_selected()

    def _editor_duplicate(self) -> None:
        self.interactive_canvas.duplicate_selected()

    def _editor_undo(self) -> None:
        self.interactive_canvas.undo()
        self._update_undo_buttons()

    def _editor_redo(self) -> None:
        self.interactive_canvas.redo()
        self._update_undo_buttons()

    def _editor_rotate_cw(self) -> None:
        self.interactive_canvas.rotate_selected(90.0)

    def _editor_rotate_ccw(self) -> None:
        self.interactive_canvas.rotate_selected(-90.0)

    def _editor_lock_selected(self) -> None:
        self.interactive_canvas.lock_selected()

    def _editor_unlock_all(self) -> None:
        self.interactive_canvas.unlock_all()

    def _update_undo_buttons(self) -> None:
        ic = self.interactive_canvas
        self._editor_undo_btn.config(state='normal' if ic.can_undo else 'disabled')
        self._editor_redo_btn.config(state='normal' if ic.can_redo else 'disabled')

    def _editor_fit(self) -> None:
        self.interactive_canvas.fit_to_entities()

    def _editor_clear(self) -> None:
        self._editor_entities.clear()
        self.interactive_canvas.set_entities(self._editor_entities)

    def _editor_export_dxf(self) -> None:
        """Export the current editor entities to a DXF file."""
        entities = self.interactive_canvas.get_entities()
        if not entities:
            messagebox.showwarning('Export', 'No entities to export.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.dxf',
            filetypes=[('DXF files', '*.dxf'), ('All files', '*.*')],
            title='Export Editor as DXF',
            initialdir=OUTPUT_DIR,
        )
        if not path:
            return
        try:
            count = em.entities_to_dxf(entities, path)
            self.status_label.config(
                text=f'Editor exported {count} entities: {path}',
                style='StatusOk.TLabel',
            )
        except Exception as exc:
            messagebox.showerror('Export Error', str(exc))

    def on_send_to_editor(self) -> None:
        """Push current preview entities to the Interactive Editor tab."""
        template_name = self.template_var.get()
        params = self._collect_params()
        try:
            entities = preview_engine.generate_preview_entities(template_name, params)
        except Exception as exc:
            messagebox.showerror('Send to Editor', f'Failed to generate geometry:\n{exc}')
            return
        # Replace editor entity list contents (keep same list object)
        self._editor_entities.clear()
        self._editor_entities.extend(entities)
        self.interactive_canvas.set_entities(self._editor_entities)
        # Switch to editor tab
        self.tab_control.select(self.editor_tab)
        self.status_label.config(
            text=f'Sent {len(entities)} entities to editor', style='StatusOk.TLabel'
        )

    # ── 3D Decompose tab ──────────────────────────────────────────────────────

    def create_3d_decompose_tab(self):
        """3D panel decomposition: enter object dimensions → get flat CNC boards."""
        outer = ttk.Frame(self.decompose_tab, padding=12)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # ── Left: scrollable inputs column ────────────────────────────────────
        left_outer, left = self._make_scrollable_panel(outer, width=300)
        left_outer.grid(row=0, column=0, sticky='nsew', padx=(0, 12))

        # Shape selector
        shape_lf = ttk.LabelFrame(left, text='3D Shape', padding=(10, 8))
        shape_lf.pack(fill='x', pady=(0, 8))

        self._decomp_shape_var = tk.StringVar(value='box')
        for val, label in (('box', 'Box (6 panels)'),
                            ('l_shape', 'L-Shape (2 panels)'),
                            ('channel', 'U-Channel (3 panels)')):
            ttk.Radiobutton(shape_lf, text=label, value=val,
                            variable=self._decomp_shape_var,
                            command=self._decomp_render_fields).pack(anchor='w', pady=2)

        # Dimension inputs
        dim_lf = ttk.LabelFrame(left, text='Dimensions (mm)', padding=(10, 8))
        dim_lf.pack(fill='x', pady=(0, 8))
        dim_lf.columnconfigure(1, weight=1)

        self._decomp_vars: Dict[str, tk.StringVar] = {}
        self._decomp_dim_frame = dim_lf   # re-rendered on shape change

        # Material
        mat_lf = ttk.LabelFrame(left, text='Material', padding=(10, 8))
        mat_lf.pack(fill='x', pady=(0, 8))
        mat_lf.columnconfigure(1, weight=1)
        ttk.Label(mat_lf, text='Thickness (mm)').grid(row=0, column=0, sticky='w', padx=(0, 8))
        self._decomp_thickness_var = tk.StringVar(value='1.5')
        ttk.Entry(mat_lf, textvariable=self._decomp_thickness_var, width=8).grid(
            row=0, column=1, sticky='ew')
        self._decomp_top_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(mat_lf, text='Include lid (box only)',
                        variable=self._decomp_top_var).grid(
            row=1, column=0, columnspan=2, sticky='w', pady=(6, 0))

        # Buttons
        btn_lf = ttk.Frame(left)
        btn_lf.pack(fill='x', pady=(0, 8))
        btn_lf.columnconfigure((0, 1), weight=1)
        ttk.Button(btn_lf, text='Decompose',
                   command=self._on_decompose).grid(row=0, column=0, sticky='ew', padx=(0, 4))
        ttk.Button(btn_lf, text='Export DXF…',
                   style='Secondary.TButton',
                   command=self._decomp_export_dxf).grid(row=0, column=1, sticky='ew')
        ttk.Button(btn_lf, text='Send to Editor ›',
                   style='Secondary.TButton',
                   command=self._decomp_send_to_editor).grid(
            row=1, column=0, columnspan=2, sticky='ew', pady=(4, 0))

        # Panel list
        panels_lf = ttk.LabelFrame(left, text='Panels', padding=(10, 8))
        panels_lf.pack(fill='both', expand=True, pady=(0, 8))
        panels_lf.rowconfigure(0, weight=1)
        panels_lf.columnconfigure(0, weight=1)

        self._decomp_listbox = tk.Listbox(
            panels_lf, height=10, exportselection=False,
            font=_FONT_UI, bg=_CLR_PANEL, relief='flat',
            selectbackground=_CLR_ACCENT, selectforeground='white',
            bd=0, highlightthickness=0,
        )
        self._decomp_listbox.grid(row=0, column=0, sticky='nsew')
        sb = ttk.Scrollbar(panels_lf, orient='vertical',
                           command=self._decomp_listbox.yview)
        sb.grid(row=0, column=1, sticky='ns')
        self._decomp_listbox.config(yscrollcommand=sb.set)
        self._decomp_listbox.bind('<<ListboxSelect>>', self._decomp_on_select)

        # Panel detail
        self._decomp_detail = ttk.Label(left, text='', style='Muted.TLabel',
                                        wraplength=320, justify='left')
        self._decomp_detail.pack(fill='x')

        # ── Right: preview ────────────────────────────────────────────────────
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky='nsew')
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        preview_lf = ttk.LabelFrame(right, text='Panel Layout Preview', padding=6)
        preview_lf.grid(row=0, column=0, sticky='nsew')
        preview_lf.rowconfigure(0, weight=1)
        preview_lf.columnconfigure(0, weight=1)

        if MATPLOTLIB_AVAILABLE:
            self._decomp_fig = Figure(figsize=(7, 5), dpi=100, facecolor=_CLR_PANEL)
            self._decomp_fig.subplots_adjust(left=0.08, right=0.97, top=0.92, bottom=0.08)
            self._decomp_ax = self._decomp_fig.add_subplot(111)
            self._decomp_mpl_canvas = FigureCanvasTkAgg(
                self._decomp_fig, master=preview_lf)
            self._decomp_mpl_canvas.get_tk_widget().grid(row=0, column=0, sticky='nsew')
        else:
            ttk.Label(preview_lf, text='Install matplotlib for panel preview',
                      style='Muted.TLabel').grid(row=0, column=0)

        # Internal state
        self._decomp_panels = []

        # Render initial fields
        self._decomp_render_fields()

    def _decomp_render_fields(self) -> None:
        """Re-render dimension input fields for the selected shape."""
        for w in self._decomp_dim_frame.winfo_children():
            w.destroy()
        self._decomp_vars.clear()

        shape = self._decomp_shape_var.get()
        field_defs = {
            'box':     [('Width (mm)',       'width'),
                        ('Depth (mm)',        'depth'),
                        ('Wall Height (mm)', 'wall_height')],
            'l_shape': [('Base Width (mm)',  'base_width'),
                        ('Base Depth (mm)',  'base_depth'),
                        ('Leg Height (mm)',  'leg_height')],
            'channel': [('Base Width (mm)',  'base_width'),
                        ('Base Depth (mm)',  'base_depth'),
                        ('Wall Height (mm)', 'wall_height')],
        }
        defaults = {
            'width': '300', 'depth': '200', 'wall_height': '100',
            'base_width': '200', 'base_depth': '100', 'leg_height': '80',
        }
        for row, (label, key) in enumerate(field_defs[shape]):
            ttk.Label(self._decomp_dim_frame, text=label).grid(
                row=row, column=0, sticky='w', pady=4, padx=(0, 8))
            var = tk.StringVar(value=defaults.get(key, '100'))
            self._decomp_vars[key] = var
            ttk.Entry(self._decomp_dim_frame, textvariable=var).grid(
                row=row, column=1, sticky='ew', pady=4)

    def _on_decompose(self) -> None:
        """Run decomposition and update listbox + preview."""
        shape = self._decomp_shape_var.get()
        try:
            thickness = float(self._decomp_thickness_var.get() or '1.5')
            fvals = {k: float(v.get()) for k, v in self._decomp_vars.items()}
        except ValueError as exc:
            messagebox.showerror('Decompose', f'Invalid input: {exc}')
            return

        try:
            if shape == 'box':
                self._decomp_panels = decompose_box(
                    width=fvals['width'], depth=fvals['depth'],
                    wall_height=fvals['wall_height'], thickness=thickness,
                    include_top=self._decomp_top_var.get(),
                )
            elif shape == 'l_shape':
                self._decomp_panels = decompose_l_shape(
                    base_width=fvals['base_width'], base_depth=fvals['base_depth'],
                    leg_height=fvals['leg_height'], thickness=thickness,
                )
            else:   # channel
                self._decomp_panels = decompose_channel(
                    base_width=fvals['base_width'], base_depth=fvals['base_depth'],
                    wall_height=fvals['wall_height'], thickness=thickness,
                )
        except ValueError as exc:
            messagebox.showerror('Decompose', str(exc))
            return

        # Update listbox
        self._decomp_listbox.delete(0, tk.END)
        for panel in self._decomp_panels:
            self._decomp_listbox.insert(
                tk.END,
                f'{panel.label}   {panel.width:.1f} × {panel.height:.1f} mm',
            )

        # Update preview
        self._decomp_update_preview()
        self.status_label.config(
            text=f'Decomposed into {len(self._decomp_panels)} panels',
            style='StatusOk.TLabel',
        )

    def _decomp_update_preview(self) -> None:
        if not MATPLOTLIB_AVAILABLE or not self._decomp_panels:
            return
        entities = panels_to_entities(self._decomp_panels)
        self._decomp_ax.clear()
        self._decomp_ax.set_facecolor('#f9fafc')
        bounds = preview_engine.render_entities(self._decomp_ax, entities)
        preview_engine.apply_ax_style(
            self._decomp_ax, 'Panel Layout', bounds,
            accent_color=_CLR_ACCENT, border_color=_CLR_BORDER,
        )
        self._decomp_mpl_canvas.draw()

    def _decomp_on_select(self, _event) -> None:
        sel = self._decomp_listbox.curselection()
        if not sel or not self._decomp_panels:
            return
        panel = self._decomp_panels[sel[0]]
        edge_lines = []
        for hint in panel.edges:
            if hint.joint != 'open':
                edge_lines.append(f'  {hint.side}: {hint.joint} → {hint.connects_to}')
        edges_str = '\n'.join(edge_lines) if edge_lines else '  (no connections)'
        self._decomp_detail.config(
            text=f'{panel.label}\n'
                 f'Size: {panel.width:.1f} W × {panel.height:.1f} H mm\n'
                 f'Thickness: {panel.thickness:.1f} mm\n'
                 f'Connections:\n{edges_str}\n'
                 f'Notes: {panel.notes}'
        )

    def _decomp_export_dxf(self) -> None:
        if not self._decomp_panels:
            messagebox.showwarning('Export', 'Run Decompose first.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.dxf',
            filetypes=[('DXF files', '*.dxf'), ('All files', '*.*')],
            title='Export Panels as DXF',
            initialdir=OUTPUT_DIR,
        )
        if not path:
            return
        try:
            panels_to_dxf(self._decomp_panels, path)
            self.status_label.config(text=f'Panels exported: {path}',
                                     style='StatusOk.TLabel')
            messagebox.showinfo('Export', f'Saved {len(self._decomp_panels)} panels to:\n{path}')
        except Exception as exc:
            messagebox.showerror('Export Error', str(exc))

    def _decomp_send_to_editor(self) -> None:
        if not self._decomp_panels:
            messagebox.showwarning('Send to Editor', 'Run Decompose first.')
            return
        entities = panels_to_entities(self._decomp_panels)
        self._editor_entities.clear()
        self._editor_entities.extend(entities)
        self.interactive_canvas.set_entities(self._editor_entities)
        self.tab_control.select(self.editor_tab)
        self.status_label.config(
            text=f'Sent {len(entities)} panel entities to editor',
            style='StatusOk.TLabel',
        )

    # ── Stacked Slicer tab ────────────────────────────────────────────────────

    def create_slicer_tab(self):
        """Tab 7 — Stacked contour slicer: STL mesh → ordered CNC boards."""
        if not SLICER_AVAILABLE:
            f = ttk.Frame(self.slicer_tab, padding=20)
            f.pack(fill='both', expand=True)
            ttk.Label(f, text='Slicer requires numpy.\n'
                               'Install with: pip install numpy').pack(pady=40)
            return

        # State
        self._slicer_triangles    = None
        self._slicer_result       = None
        self._slicer_sheet_layout = None

        outer = ttk.Frame(self.slicer_tab, padding=10)
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)

        # ── Left: scrollable controls column ──────────────────────────────────
        left_outer, left = self._make_scrollable_panel(outer, width=280)
        left_outer.grid(row=0, column=0, sticky='nsew', padx=(0, 10))

        # File
        file_lf = ttk.LabelFrame(left, text='STL File', padding=(10, 8))
        file_lf.pack(fill='x', pady=(0, 8))
        self._slicer_path_var = tk.StringVar(value='')
        ttk.Entry(file_lf, textvariable=self._slicer_path_var,
                  state='readonly', width=30).pack(fill='x', pady=(0, 4))
        ttk.Button(file_lf, text='Browse STL…',
                   command=self._slicer_browse).pack(fill='x')

        # Stacking axis
        axis_lf = ttk.LabelFrame(left, text='Slicing Direction', padding=(10, 8))
        axis_lf.pack(fill='x', pady=(0, 8))
        self._slicer_axis_var = tk.StringVar(value='y')
        _AXIS_CHOICES = (
            ('y', 'Along Y  →  boards in X-Z plane', '(stack top-to-bottom)'),
            ('x', 'Along X  →  boards in Y-Z plane', '(stack left-to-right)'),
            ('z', 'Along Z  →  boards in X-Y plane', '(stack front-to-back)'),
        )
        for ax, label, sublabel in _AXIS_CHOICES:
            row = ttk.Frame(axis_lf)
            row.pack(fill='x', pady=1)
            ttk.Radiobutton(row, text=label, value=ax,
                            variable=self._slicer_axis_var,
                            command=self._slicer_on_axis_change).pack(
                side='left', anchor='w')
            ttk.Label(row, text=sublabel, style='Muted.TLabel',
                      font=('Segoe UI', 8)).pack(side='left', padx=(4, 0))

        # Axis note
        ttk.Label(axis_lf,
                  text='Each board is a flat CNC-cut cross-section.\n'
                       'Boards stack together to form the 3D shape.',
                  style='Muted.TLabel', wraplength=240,
                  justify='left').pack(anchor='w', pady=(6, 0))

        # Slice mode
        mode_lf = ttk.LabelFrame(left, text='Slice Mode', padding=(10, 8))
        mode_lf.pack(fill='x', pady=(0, 8))
        mode_lf.columnconfigure(1, weight=1)

        self._slicer_mode_var = tk.StringVar(value='thickness')

        # — thickness mode —
        ttk.Radiobutton(mode_lf, text='Fixed board thickness',
                        value='thickness', variable=self._slicer_mode_var,
                        command=self._slicer_toggle_mode).grid(
            row=0, column=0, columnspan=2, sticky='w')
        row_t = ttk.Frame(mode_lf)
        row_t.grid(row=1, column=0, columnspan=2, sticky='ew', padx=(14, 0), pady=(2, 6))
        row_t.columnconfigure(1, weight=1)
        ttk.Label(row_t, text='Thickness (mm)').grid(row=0, column=0, sticky='w')
        self._slicer_thickness_var = tk.StringVar(value='20')
        ttk.Entry(row_t, textvariable=self._slicer_thickness_var,
                  width=8).grid(row=0, column=1, sticky='w', padx=(6, 0))
        self._slicer_computed_count_var = tk.StringVar(value='')
        ttk.Label(row_t, textvariable=self._slicer_computed_count_var,
                  style='Muted.TLabel').grid(row=1, column=0, columnspan=2, sticky='w')

        # — count mode —
        ttk.Radiobutton(mode_lf, text='Fixed number of boards',
                        value='count', variable=self._slicer_mode_var,
                        command=self._slicer_toggle_mode).grid(
            row=2, column=0, columnspan=2, sticky='w')
        row_c = ttk.Frame(mode_lf)
        row_c.grid(row=3, column=0, columnspan=2, sticky='ew', padx=(14, 0), pady=(2, 0))
        row_c.columnconfigure(1, weight=1)
        ttk.Label(row_c, text='Board count').grid(row=0, column=0, sticky='w')
        self._slicer_count_var = tk.StringVar(value='5')
        self._slicer_count_entry = ttk.Entry(
            row_c, textvariable=self._slicer_count_var, width=8)
        self._slicer_count_entry.grid(row=0, column=1, sticky='w', padx=(6, 0))
        self._slicer_computed_thick_var = tk.StringVar(value='')
        ttk.Label(row_c, textvariable=self._slicer_computed_thick_var,
                  style='Muted.TLabel').grid(row=1, column=0, columnspan=2, sticky='w')

        # Board profile mode
        profile_lf = ttk.LabelFrame(left, text='Board Profile Mode', padding=(10, 8))
        profile_lf.pack(fill='x', pady=(0, 8))
        self._slicer_slab_mode_var = tk.StringVar(value='envelope')

        # ── Envelope (recommended / default) ─────────────────────────────────
        ttk.Radiobutton(
            profile_lf, text='Full slab envelope  \u2605 recommended',
            value='envelope', variable=self._slicer_slab_mode_var,
        ).pack(anchor='w')
        ttk.Label(
            profile_lf,
            text='Board profile = union of all cross-sections\n'
                 'across the full slab thickness.  Correct for\n'
                 'every shape, including organic, hollow, crescent,\n'
                 'and branching forms.  ~1\u20132 s per board.\n'
                 'Use this for fabrication.',
            style='Muted.TLabel', wraplength=235, justify='left',
        ).pack(anchor='w', padx=(14, 0), pady=(0, 8))

        # ── Best cross-section (fast alternative) ────────────────────────────
        ttk.Radiobutton(
            profile_lf, text='Best cross-section  (fast)',
            value='best_sample', variable=self._slicer_slab_mode_var,
        ).pack(anchor='w')
        ttk.Label(
            profile_lf,
            text='Picks the single widest plane inside each slab.\n'
                 'Only use for simple shapes (box, cylinder, cone)\n'
                 'or when speed matters more than accuracy.',
            style='Muted.TLabel', wraplength=235, justify='left',
        ).pack(anchor='w', padx=(14, 0))

        # ── Quality preset ────────────────────────────────────────────────────
        q_row = ttk.Frame(profile_lf)
        q_row.pack(fill='x', pady=(8, 0))
        ttk.Label(q_row, text='Quality:', font=_FONT_BOLD).pack(side='left')
        self._slicer_quality_var = tk.StringVar(value='accurate')
        ttk.Radiobutton(q_row, text='Accurate', value='accurate',
                        variable=self._slicer_quality_var).pack(side='left', padx=(8, 0))
        ttk.Radiobutton(q_row, text='Fast', value='fast',
                        variable=self._slicer_quality_var).pack(side='left', padx=(8, 0))
        ttk.Label(profile_lf,
                  text='Fast: 3 samples, 60×60 grid — good for quick layout checks.\n'
                       'Accurate: 7 samples, 120×120 — use for final fabrication DXF.',
                  style='Muted.TLabel', wraplength=235, justify='left',
                  ).pack(anchor='w', pady=(2, 0))

        # Layout spacing
        layout_lf = ttk.LabelFrame(left, text='DXF Layout', padding=(10, 8))
        layout_lf.pack(fill='x', pady=(0, 8))
        layout_lf.columnconfigure(1, weight=1)
        ttk.Label(layout_lf, text='Board gap (mm)').grid(row=0, column=0, sticky='w')
        self._slicer_gap_var = tk.StringVar(value='20')
        ttk.Entry(layout_lf, textvariable=self._slicer_gap_var,
                  width=8).grid(row=0, column=1, sticky='ew', padx=(4, 0))

        # Sheet layout
        sheet_lf = ttk.LabelFrame(left, text='Sheet Layout  (optional)', padding=(10, 8))
        sheet_lf.pack(fill='x', pady=(0, 8))
        sheet_lf.columnconfigure(1, weight=1)

        ttk.Label(sheet_lf, text='Sheet width (mm)').grid(row=0, column=0, sticky='w')
        self._slicer_sheet_w_var = tk.StringVar(value='')
        ttk.Entry(sheet_lf, textvariable=self._slicer_sheet_w_var,
                  width=10).grid(row=0, column=1, sticky='w', padx=(4, 0))

        ttk.Label(sheet_lf, text='Sheet height (mm)').grid(row=1, column=0, sticky='w', pady=(4, 0))
        self._slicer_sheet_h_var = tk.StringVar(value='')
        ttk.Entry(sheet_lf, textvariable=self._slicer_sheet_h_var,
                  width=10).grid(row=1, column=1, sticky='w', padx=(4, 0), pady=(4, 0))

        ttk.Label(sheet_lf, text='Spacing (mm)').grid(row=2, column=0, sticky='w')
        self._slicer_sheet_sp_var = tk.StringVar(value='10')
        ttk.Entry(sheet_lf, textvariable=self._slicer_sheet_sp_var,
                  width=10).grid(row=2, column=1, sticky='w', padx=(4, 0))

        self._slicer_sheet_info_var = tk.StringVar(value='Enter sheet size to enable layout.')
        ttk.Label(sheet_lf, textvariable=self._slicer_sheet_info_var,
                  style='Muted.TLabel', wraplength=235, justify='left').grid(
            row=3, column=0, columnspan=2, sticky='w', pady=(6, 0))

        ttk.Label(sheet_lf,
                  text='Leave blank to use linear strip layout.',
                  style='Muted.TLabel', wraplength=235).grid(
            row=4, column=0, columnspan=2, sticky='w', pady=(2, 0))

        # Alignment
        align_lf = ttk.LabelFrame(left, text='Alignment / Registration',
                                   padding=(10, 8))
        align_lf.pack(fill='x', pady=(0, 8))
        align_lf.columnconfigure(1, weight=1)

        self._slicer_center_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(align_lf, text='Centre mark on every board',
                        variable=self._slicer_center_var).grid(
            row=0, column=0, columnspan=2, sticky='w')

        self._slicer_dowels_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(align_lf, text='Dowel / alignment holes',
                        variable=self._slicer_dowels_var).grid(
            row=1, column=0, columnspan=2, sticky='w', pady=(4, 0))

        # n_holes radiobuttons
        holes_row = ttk.Frame(align_lf)
        holes_row.grid(row=2, column=0, columnspan=2, sticky='w', pady=(2, 0))
        ttk.Label(holes_row, text='# holes:').pack(side='left')
        self._slicer_nholes_var = tk.IntVar(value=4)
        for n, label in [(2, '2'), (3, '3'), (4, '4')]:
            ttk.Radiobutton(holes_row, text=label,
                            variable=self._slicer_nholes_var,
                            value=n).pack(side='left', padx=(6, 0))

        ttk.Label(align_lf, text='Dowel radius (mm)').grid(
            row=3, column=0, sticky='w', pady=(4, 0))
        self._slicer_dowel_r_var = tk.StringVar(value='3.0')
        ttk.Entry(align_lf, textvariable=self._slicer_dowel_r_var,
                  width=8).grid(row=3, column=1, sticky='w', padx=(4, 0), pady=(4, 0))

        ttk.Label(align_lf, text='Edge margin (mm)').grid(
            row=4, column=0, sticky='w')
        self._slicer_margin_var = tk.StringVar(value='')
        ttk.Entry(align_lf, textvariable=self._slicer_margin_var,
                  width=8).grid(row=4, column=1, sticky='w', padx=(4, 0))

        ttk.Label(align_lf,
                  text='Edge margin: distance from board edge to hole\n'
                       'centre. Leave blank for auto (20 % inset).\n'
                       'Holes outside a board profile are skipped.',
                  style='Muted.TLabel', wraplength=235, justify='left').grid(
            row=5, column=0, columnspan=2, sticky='w', pady=(4, 0))

        # Info panel (computed stats)
        info_lf = ttk.LabelFrame(left, text='Computed Info', padding=(10, 8))
        info_lf.pack(fill='x', pady=(0, 8))
        self._slicer_info_var = tk.StringVar(value='Load an STL to begin.')
        ttk.Label(info_lf, textvariable=self._slicer_info_var,
                  style='Muted.TLabel', justify='left',
                  wraplength=240).pack(fill='x')

        # ── Primary action: Slice button + progress bar ───────────────────────
        slice_btn_frame = ttk.Frame(left)
        slice_btn_frame.pack(fill='x', pady=(0, 4))
        self._slicer_btn = ttk.Button(slice_btn_frame, text='▶  Slice',
                                      command=self._slicer_run)
        self._slicer_btn.pack(fill='x', ipady=4)

        self._slicer_progress_var = tk.DoubleVar(value=0)
        self._slicer_progress_bar = ttk.Progressbar(
            left, variable=self._slicer_progress_var,
            maximum=100, mode='determinate')
        # Hidden until slicing starts; pack_forget() is called after done
        self._slicer_progress_bar.pack(fill='x', pady=(0, 4))
        self._slicer_progress_bar.pack_forget()

        # Slice listbox (fixed height — does NOT expand so buttons stay visible)
        list_lf = ttk.LabelFrame(left, text='Slices', padding=(10, 8))
        list_lf.pack(fill='x', pady=(0, 8))
        list_lf.columnconfigure(0, weight=1)
        self._slicer_listbox = tk.Listbox(
            list_lf, height=6, exportselection=False,
            font=_FONT_UI, bg=_CLR_PANEL, relief='flat',
            selectbackground=_CLR_ACCENT, selectforeground='white',
            bd=0, highlightthickness=0,
        )
        self._slicer_listbox.grid(row=0, column=0, sticky='nsew')
        sb2 = ttk.Scrollbar(list_lf, orient='vertical',
                            command=self._slicer_listbox.yview)
        sb2.grid(row=0, column=1, sticky='ns')
        self._slicer_listbox.config(yscrollcommand=sb2.set)
        self._slicer_listbox.bind('<<ListboxSelect>>', self._slicer_on_select)

        # Board navigation slider — hidden until a result is loaded
        self._slicer_slider_var = tk.IntVar(value=1)
        self._slicer_board_slider = tk.Scale(
            list_lf, from_=1, to=1, orient='horizontal',
            variable=self._slicer_slider_var,
            command=self._slicer_on_slider,
            showvalue=True, label='Board',
            bg=_CLR_PANEL, troughcolor=_CLR_BORDER,
            highlightthickness=0, font=_FONT_UI,
            relief='flat', bd=0,
        )
        self._slicer_board_slider.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4, 0))

        # Export / send actions
        btn_lf = ttk.LabelFrame(left, text='Export', padding=(10, 8))
        btn_lf.pack(fill='x', pady=(0, 4))
        btn_lf.columnconfigure((0, 1), weight=1)

        ttk.Button(btn_lf, text='Export All Boards (combined DXF)…',
                   style='Secondary.TButton',
                   command=self._slicer_export_dxf).grid(
            row=0, column=0, columnspan=2, sticky='ew', pady=(0, 4))
        ttk.Button(btn_lf, text='Export Per-Board DXF…',
                   style='Secondary.TButton',
                   command=self._slicer_export_per_board).grid(
            row=1, column=0, columnspan=2, sticky='ew', pady=(0, 4))
        ttk.Button(btn_lf, text='Send All to Editor ›',
                   style='Secondary.TButton',
                   command=self._slicer_send_all).grid(
            row=2, column=0, sticky='ew', padx=(0, 4))
        ttk.Button(btn_lf, text='Send Selected ›',
                   style='Secondary.TButton',
                   command=self._slicer_send_selected).grid(
            row=2, column=1, sticky='ew')

        # ── Right: preview area ────────────────────────────────────────────────
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky='nsew')
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        # Mode toggle bar
        toggle_bar = ttk.Frame(right)
        toggle_bar.grid(row=0, column=0, sticky='ew', pady=(0, 4))
        ttk.Label(toggle_bar, text='Preview:', font=_FONT_BOLD).pack(side='left', padx=(0, 8))
        self._slicer_preview_mode = tk.StringVar(value='2d')
        ttk.Radiobutton(toggle_bar, text='2D Layout', value='2d',
                        variable=self._slicer_preview_mode,
                        command=self._slicer_switch_preview).pack(side='left', padx=(0, 4))
        ttk.Radiobutton(toggle_bar, text='3D Reconstruction', value='3d',
                        variable=self._slicer_preview_mode,
                        command=self._slicer_switch_preview).pack(side='left')
        ttk.Radiobutton(toggle_bar, text='Overlay', value='overlay',
                        variable=self._slicer_preview_mode,
                        command=self._slicer_switch_preview).pack(side='left', padx=(4, 0))
        ttk.Label(toggle_bar, text='  (drag 3D to rotate)',
                  style='Muted.TLabel', font=('Segoe UI', 8)).pack(side='left', padx=(8, 0))
        ttk.Label(toggle_bar, text='   Step:',
                  style='Muted.TLabel').pack(side='left')
        self._slicer_step_var = tk.IntVar(value=1)
        ttk.Spinbox(toggle_bar, from_=1, to=50,
                    textvariable=self._slicer_step_var,
                    width=3, command=self._slicer_redraw_current).pack(side='left', padx=(2, 0))

        # Shared container that holds whichever canvas is active
        self._slicer_preview_container = ttk.Frame(right)
        self._slicer_preview_container.grid(row=1, column=0, sticky='nsew')
        self._slicer_preview_container.rowconfigure(0, weight=1)
        self._slicer_preview_container.columnconfigure(0, weight=1)

        if MATPLOTLIB_AVAILABLE:
            from mpl_toolkits.mplot3d import Axes3D  # noqa: F401 — registers 3d projection

            # ── 2D layout canvas ─────────────────────────────────────────────
            self._slicer_fig_2d = Figure(figsize=(7, 5), dpi=96)
            self._slicer_ax_2d  = self._slicer_fig_2d.add_subplot(111)
            self._slicer_fig_2d.patch.set_facecolor('#f9fafc')
            self._slicer_canvas_2d = FigureCanvasTkAgg(
                self._slicer_fig_2d, master=self._slicer_preview_container)
            self._slicer_canvas_2d.get_tk_widget().grid(row=0, column=0, sticky='nsew')

            # ── 3D reconstruction canvas ─────────────────────────────────────
            self._slicer_fig_3d = Figure(figsize=(7, 5), dpi=96)
            self._slicer_ax_3d  = self._slicer_fig_3d.add_subplot(111, projection='3d')
            self._slicer_fig_3d.patch.set_facecolor('#f9fafc')
            self._slicer_canvas_3d = FigureCanvasTkAgg(
                self._slicer_fig_3d, master=self._slicer_preview_container)
            # 3D canvas starts hidden; 2D is default
            self._slicer_canvas_3d.get_tk_widget().grid(row=0, column=0, sticky='nsew')
            self._slicer_canvas_3d.get_tk_widget().grid_remove()

            # Keep backward-compat references used by existing draw methods
            self._slicer_fig = self._slicer_fig_2d
            self._slicer_ax  = self._slicer_ax_2d
            self._slicer_canvas_mpl = self._slicer_canvas_2d
        else:
            ttk.Label(self._slicer_preview_container,
                      text='Matplotlib not available — install for preview.'
                      ).grid(row=0, column=0, pady=30)

        self._slicer_toggle_mode()   # initial field enable/disable state

    def _slicer_toggle_mode(self) -> None:
        """Grey out the unused input field based on selected mode."""
        mode = self._slicer_mode_var.get()
        state_count = 'normal' if mode == 'count' else 'disabled'
        self._slicer_count_entry.config(state=state_count)

    def _slicer_on_axis_change(self) -> None:
        """Clear both previews when axis changes so stale data is never shown."""
        if self._slicer_result is None:
            return
        if not MATPLOTLIB_AVAILABLE:
            return
        axis = self._slicer_axis_var.get()
        plane, h, v = _slicer_mod.board_plane_info(axis)
        msg = (f'Axis changed → {axis.upper()}  (boards in {plane} plane)\n'
               'Press  Slice  to update.')

        self._slicer_ax_2d.clear()
        self._slicer_ax_2d.text(0.5, 0.5, msg, ha='center', va='center',
                                transform=self._slicer_ax_2d.transAxes,
                                fontsize=10, color='#888', style='italic')
        self._slicer_ax_2d.axis('off')
        self._slicer_canvas_2d.draw()

        self._slicer_ax_3d.clear()
        self._slicer_ax_3d.text(0.5, 0.5, 0.5, msg, ha='center', va='center',
                                fontsize=9, color='#888', style='italic')
        self._slicer_canvas_3d.draw()

        # Invalidate result so old data can't be exported
        self._slicer_result = None

    def _slicer_switch_preview(self) -> None:
        """Show/hide canvases based on current mode toggle."""
        if not MATPLOTLIB_AVAILABLE:
            return
        mode = self._slicer_preview_mode.get()
        # Hide both first
        self._slicer_canvas_2d.get_tk_widget().grid_remove()
        self._slicer_canvas_3d.get_tk_widget().grid_remove()
        if mode == '2d':
            self._slicer_canvas_2d.get_tk_widget().grid()
            if self._slicer_result is not None:
                self._slicer_draw_preview(gap=self._slicer_gap_try_float())
        elif mode == '3d':
            self._slicer_canvas_3d.get_tk_widget().grid()
            sel = self._slicer_listbox.curselection()
            self._slicer_draw_3d_preview(selected_idx=sel[0] if sel else None)
        else:  # 'overlay'
            self._slicer_canvas_2d.get_tk_widget().grid()
            self._slicer_draw_overlay_preview()

    def _slicer_draw_3d_preview(self, selected_idx: Optional[int] = None) -> None:
        """
        3D slab-stack reconstruction.

        Each board is drawn as a volumetric slab between its y_min and y_max
        planes (bottom face + top face + side walls), giving the appearance of
        physically cut boards stacked along the chosen axis.

        set_box_aspect enforces correct world proportions so a 100×60 mm
        rectangle looks rectangular (not square) in the viewport.
        """
        if not MATPLOTLIB_AVAILABLE or self._slicer_result is None:
            return

        from mpl_toolkits.mplot3d.art3d import Poly3DCollection

        result        = self._slicer_result
        stacking_axis = result.stacking_axis
        ax3           = self._slicer_ax_3d
        ax3.clear()
        ax3.set_facecolor('#f0f4f8')

        plane_name, h_axis, v_axis = _slicer_mod.board_plane_info(stacking_axis)
        import matplotlib.cm as _cm

        _CLR_RIB   = '#78909c'   # centroid spine
        _CLR_SEL_E = '#e53935'   # selected outline (bright red)
        _CLR_SEL_F = '#ffcdd2'   # selected fill

        # Per-board colormap: tab20b gives 20 distinct hues, cycles for >20 boards
        n_slices   = len(result.slices)
        try:
            _cmap_fill = _cm.colormaps.get_cmap('tab20b').resampled(max(n_slices, 2))
            _cmap_edge = _cm.colormaps.get_cmap('tab20').resampled(max(n_slices, 2))
        except AttributeError:   # matplotlib < 3.7
            _cmap_fill = _cm.get_cmap('tab20b', max(n_slices, 2))
            _cmap_edge = _cm.get_cmap('tab20',  max(n_slices, 2))

        def _board_fill_color(board_idx: int):
            c = _cmap_fill(board_idx % max(n_slices, 1))
            return (c[0], c[1], c[2])   # RGB tuple, no alpha (controlled separately)

        def _board_edge_color(board_idx: int):
            c = _cmap_edge(board_idx % max(n_slices, 1))
            # Darken slightly for edge vs fill
            return (c[0] * 0.7, c[1] * 0.7, c[2] * 0.7)

        def _world_face(contour, y_val, axis):
            """Map board (a,b) → world (X,Y,Z) at a fixed axis position."""
            if axis == 'y':
                return [(p[0], y_val, p[1]) for p in contour]
            elif axis == 'x':
                return [(y_val, p[0], p[1]) for p in contour]
            else:   # 'z'
                return [(p[0], p[1], y_val) for p in contour]

        all_wx, all_wy, all_wz = [], [], []
        centroids: list = []

        for board_draw_idx, sl in enumerate(result.slices):
            if not sl.contours:
                continue

            is_sel = (selected_idx is not None and sl.index == selected_idx)
            # Draw all contours for this board (outer shell + any disconnected parts)
            sorted_c = sorted(sl.contours, key=_slicer_mod._contour_area, reverse=True)

            # Per-board colors (overridden to red when selected)
            face_col   = _CLR_SEL_F if is_sel else _board_fill_color(board_draw_idx)
            edge_col   = _CLR_SEL_E if is_sel else _board_edge_color(board_draw_idx)
            face_alpha = 0.55       if is_sel else 0.28
            edge_lw    = 2.8        if is_sel else 1.4

            y_lo = sl.y_min
            y_hi = sl.y_max

            # Only the outer (largest) contour contributes to the centroid spine.
            outer = sorted_c[0]
            y_mid = (y_lo + y_hi) / 2.0
            ca = sum(p[0] for p in outer) / len(outer)
            cb = sum(p[1] for p in outer) / len(outer)
            if stacking_axis == 'y':
                centroids.append((ca, y_mid, cb))
            elif stacking_axis == 'x':
                centroids.append((y_mid, ca, cb))
            else:
                centroids.append((ca, cb, y_mid))

            # Draw each contour as a slab (top + bottom + sides)
            for contour in sorted_c:
                bot_face = _world_face(contour, y_lo, stacking_axis)
                top_face = _world_face(contour, y_hi, stacking_axis)

                for pt in bot_face + top_face:
                    all_wx.append(pt[0]); all_wy.append(pt[1]); all_wz.append(pt[2])

                # ── Top + bottom filled faces ─────────────────────────────────
                poly_faces = Poly3DCollection(
                    [bot_face, top_face],
                    facecolors=[face_col], edgecolors='none', alpha=face_alpha,
                )
                ax3.add_collection3d(poly_faces)

                # ── Side walls (sparse quads around perimeter) ────────────────
                n    = len(contour)
                step = max(1, n // min(n, 24))   # ≤24 quads
                side_polys = []
                for k in range(0, n, step):
                    j = (k + step) % n
                    side_polys.append([bot_face[k], bot_face[j],
                                        top_face[j], top_face[k]])
                if side_polys:
                    ax3.add_collection3d(Poly3DCollection(
                        side_polys, facecolors=[face_col],
                        edgecolors='none', alpha=face_alpha * 0.55,
                    ))

                # ── Dominant outlines: top and bottom edges ───────────────────
                for face_pts in (bot_face, top_face):
                    wxf = [p[0] for p in face_pts] + [face_pts[0][0]]
                    wyf = [p[1] for p in face_pts] + [face_pts[0][1]]
                    wzf = [p[2] for p in face_pts] + [face_pts[0][2]]
                    ax3.plot3D(wxf, wyf, wzf,
                               color=edge_col, linewidth=edge_lw,
                               zorder=5 if is_sel else 3)

                # ── Sparse vertical corner lines (depth cue) ──────────────────
                n_corners = min(8, n)
                step_c    = max(1, n // n_corners)
                for k in range(0, n, step_c):
                    b, t = bot_face[k], top_face[k]
                    ax3.plot3D([b[0], t[0]], [b[1], t[1]], [b[2], t[2]],
                               color=edge_col, linewidth=0.7,
                               alpha=0.50, zorder=2)

        # ── Centroid rib spine ────────────────────────────────────────────────
        if len(centroids) >= 2:
            cx = [c[0] for c in centroids]
            cy = [c[1] for c in centroids]
            cz = [c[2] for c in centroids]
            ax3.plot3D(cx, cy, cz, color=_CLR_RIB, linewidth=0.8,
                       linestyle='--', alpha=0.6, zorder=1)

        # ── Correct aspect ratio ──────────────────────────────────────────────
        def _span(vals):
            return max(max(vals) - min(vals), 1.0) if vals else 1.0

        def _centre(vals):
            return (max(vals) + min(vals)) / 2.0 if vals else 0.0

        xspan = _span(all_wx)
        yspan = _span(all_wy)
        zspan = _span(all_wz)
        mx    = max(xspan, yspan, zspan)

        half = mx * 0.55
        xc = _centre(all_wx); yc = _centre(all_wy); zc = _centre(all_wz)
        ax3.set_xlim3d(xc - half, xc + half)
        ax3.set_ylim3d(yc - half, yc + half)
        ax3.set_zlim3d(zc - half, zc + half)

        try:
            ax3.set_box_aspect([xspan / mx, yspan / mx, zspan / mx])
        except AttributeError:
            pass   # matplotlib < 3.3

        try:
            ax3.view_init(elev=22, azim=self._SLICER_VIEW_AZIM.get(stacking_axis, 35))
        except Exception:
            pass

        # ── Axis labels ───────────────────────────────────────────────────────
        stack_lbl = f'{stacking_axis.upper()} ← stack'
        if stacking_axis == 'y':
            ax3.set_xlabel(f'X ({h_axis})', fontsize=7)
            ax3.set_ylabel(stack_lbl, fontsize=7)
            ax3.set_zlabel(f'Z ({v_axis})', fontsize=7)
        elif stacking_axis == 'x':
            ax3.set_xlabel(stack_lbl, fontsize=7)
            ax3.set_ylabel(f'Y ({h_axis})', fontsize=7)
            ax3.set_zlabel(f'Z ({v_axis})', fontsize=7)
        else:
            ax3.set_xlabel(f'X ({h_axis})', fontsize=7)
            ax3.set_ylabel(f'Y ({v_axis})', fontsize=7)
            ax3.set_zlabel(stack_lbl, fontsize=7)

        ax3.tick_params(labelsize=6)

        sel_note  = f'  ·  board {selected_idx + 1} selected' if selected_idx is not None else ''
        mode_note = '  ·  envelope' if result.slab_mode == 'envelope' else ''
        ax3.set_title(
            f'{result.n_boards} boards  ·  {result.board_thickness:.1f} mm thick  ·  '
            f'axis {stacking_axis.upper()}  ·  {plane_name}{mode_note}{sel_note}',
            fontsize=8, color='#333', pad=4)

        self._slicer_fig_3d.tight_layout(pad=0.8)
        self._slicer_canvas_3d.draw()


# Per-axis default azimuth for a good initial viewing angle
    # Per-axis default azimuth (degrees) for a good initial 3D view angle
    _SLICER_VIEW_AZIM = {'y': 35, 'x': 125, 'z': 35}

    def _slicer_draw_overlay_preview(self, highlight_idx: Optional[int] = None) -> None:
        """
        Overlay diagnostic: all board outer contours drawn centred at the
        origin with different colours.  Confirms shape variation across slices.
        """
        if not MATPLOTLIB_AVAILABLE or self._slicer_result is None:
            return
        import matplotlib.cm as cm

        result = self._slicer_result
        ax = self._slicer_ax_2d
        ax.clear()
        ax.set_facecolor('#f9fafc')
        ax.set_aspect('equal')

        slices = result.slices
        n = len(slices)
        try:
            cmap = cm.colormaps.get_cmap('plasma').resampled(max(n, 2))
        except AttributeError:
            cmap = cm.get_cmap('plasma', max(n, 2))

        for i, sl in enumerate(slices):
            if not sl.contours:
                continue
            outer = max(sl.contours, key=_slicer_mod._contour_area)
            xs = [p[0] for p in outer]
            zs = [p[1] for p in outer]
            color = cmap(i / max(n - 1, 1))
            lw = 2.5 if i == highlight_idx else 1.0
            alpha_fill = 0.15 if i != highlight_idx else 0.35
            ax.plot(xs + [xs[0]], zs + [zs[0]], color=color, lw=lw,
                    label=f'Bd {i+1}' if i % max(1, n//8) == 0 else '')
            ax.fill(xs, zs, color=color, alpha=alpha_fill)

        plane_name, h_axis, v_axis = _slicer_mod.board_plane_info(result.stacking_axis)
        ax.set_xlabel(f'{h_axis} →', fontsize=8)
        ax.set_ylabel(f'{v_axis} ↑', fontsize=8)
        ax.set_title(
            f'Contour overlay — {n} boards, axis {result.stacking_axis.upper()}\n'
            f'(warm colour = first board, cool = last; shape change = correct slicing)',
            fontsize=8, color='#333')
        ax.tick_params(labelsize=6)
        if n <= 12:
            ax.legend(fontsize=6, loc='upper right', framealpha=0.7)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        self._slicer_fig_2d.tight_layout(pad=0.8)
        self._slicer_canvas_2d.draw()

    def _slicer_browse(self) -> None:
        path = filedialog.askopenfilename(
            title='Open STL File',
            filetypes=[('STL files', '*.stl'), ('All files', '*.*')],
        )
        if not path:
            return
        try:
            self._slicer_triangles = _slicer_mod.load_mesh(path)
            self._slicer_path_var.set(os.path.basename(path))
            n = len(self._slicer_triangles)
            self.status_label.config(
                text=f'STL loaded: {n} triangles — {os.path.basename(path)}',
                style='StatusOk.TLabel',
            )
            # Show mesh bounds in info panel
            import numpy as np
            v = self._slicer_triangles.reshape(-1, 3)
            self._slicer_info_var.set(
                f'Triangles: {n}\n'
                f'X: {v[:,0].min():.1f} → {v[:,0].max():.1f} mm\n'
                f'Y: {v[:,1].min():.1f} → {v[:,1].max():.1f} mm\n'
                f'Z: {v[:,2].min():.1f} → {v[:,2].max():.1f} mm'
            )
        except Exception as exc:
            messagebox.showerror('Load Error', f'Failed to load STL:\n{exc}')

    def _slicer_run(self) -> None:
        """Validate inputs, disable UI, start slicing in a background thread."""
        if self._slicer_triangles is None:
            messagebox.showwarning('Slice', 'Load an STL file first.')
            return
        try:
            # Snapshot all params before the thread starts (avoids race conditions)
            params = {
                'axis':       self._slicer_axis_var.get(),
                'gap':        float(self._slicer_gap_var.get()),
                'slab_mode':  self._slicer_slab_mode_var.get(),
                'quality':    self._slicer_quality_var.get(),
                'slice_mode': self._slicer_mode_var.get(),
                'thickness':  float(self._slicer_thickness_var.get()),
                'n_boards':   int(self._slicer_count_var.get()),
                'margin_s':   self._slicer_margin_var.get().strip(),
                'dowel_r':    float(self._slicer_dowel_r_var.get()),
                'n_holes':    self._slicer_nholes_var.get(),
                'center_mark': self._slicer_center_var.get(),
                'add_dowels': self._slicer_dowels_var.get(),
                'sheet_w':    self._slicer_sheet_w_var.get(),
                'sheet_h':    self._slicer_sheet_h_var.get(),
                'sheet_sp':   self._slicer_sheet_sp_var.get() or '10',
            }
        except ValueError as exc:
            messagebox.showerror('Slice Error', f'Invalid input: {exc}')
            return

        # Disable button; show progress bar
        self._slicer_btn.config(state='disabled', text='Slicing…')
        self._slicer_progress_var.set(0)
        self._slicer_progress_bar.pack(fill='x', pady=(0, 4),
                                       before=self._slicer_listbox.master)
        self.status_label.config(text='Slicing… (board 0 / ?)',
                                 style='StatusOk.TLabel')

        triangles = self._slicer_triangles

        def _progress(done: int, total: int) -> None:
            pct = 100.0 * done / max(total, 1)
            self.after(0, lambda p=pct, d=done, t=total: (
                self._slicer_progress_var.set(p),
                self.status_label.config(
                    text=f'Slicing… board {d} / {t}',
                    style='StatusOk.TLabel'),
            ))

        def _worker() -> None:
            try:
                axis      = params['axis']
                slab_mode = params['slab_mode']
                quality   = params['quality']
                if params['slice_mode'] == 'thickness':
                    result = _slicer_mod.slice_model(
                        triangles, params['thickness'],
                        stacking_axis=axis, slab_mode=slab_mode,
                        quality=quality, progress_callback=_progress)
                else:
                    result = _slicer_mod.slice_model_by_count(
                        triangles, params['n_boards'],
                        stacking_axis=axis, slab_mode=slab_mode,
                        quality=quality, progress_callback=_progress)
                self.after(0, lambda r=result: self._slicer_run_done(r, params))
            except Exception as exc:
                self.after(0, lambda e=str(exc): self._slicer_run_error(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _slicer_run_error(self, msg: str) -> None:
        """Called on main thread when the slice worker fails."""
        self._slicer_btn.config(state='normal', text='▶  Slice')
        self._slicer_progress_bar.pack_forget()
        messagebox.showerror('Slice Error', msg)

    def _slicer_run_done(self, result, params: dict) -> None:
        """Called on main thread when slicing succeeds."""
        self._slicer_btn.config(state='normal', text='▶  Slice')
        self._slicer_progress_bar.pack_forget()

        axis      = params['axis']
        gap       = params['gap']
        slab_mode = params['slab_mode']

        if params['slice_mode'] == 'thickness':
            self._slicer_computed_count_var.set(f'\u2192 {result.n_boards} boards')
            self._slicer_computed_thick_var.set('')
        else:
            self._slicer_computed_thick_var.set(
                f'\u2192 {result.board_thickness:.2f} mm / board')
            self._slicer_computed_count_var.set('')

        # Alignment geometry (fast — runs on main thread)
        edge_margin = float(params['margin_s']) if params['margin_s'] else None
        _slicer_mod.add_alignment_geometry(
            result,
            dowel_radius=params['dowel_r'],
            n_holes=params['n_holes'],
            edge_margin_mm=edge_margin,
            add_center_mark=params['center_mark'],
            add_dowels=params['add_dowels'],
        )

        self._slicer_result = result

        # Sheet layout stats
        try:
            sw  = float(params['sheet_w'])
            sh  = float(params['sheet_h'])
            sp  = float(params['sheet_sp'])
            slr = _slicer_mod.sheet_layout(result, sw, sh, spacing=sp)
            used_pct  = sum(pl.width * pl.height for pl in slr.placements)
            sheet_area = sw * sh
            if slr.n_sheets > 0:
                pct        = min(100.0, 100 * used_pct / (slr.n_sheets * sheet_area))
                sheet_info = (f'{slr.n_sheets} sheet(s)  ·  '
                              f'{len(slr.placements)} boards placed\n'
                              f'Area utilisation: {pct:.0f} %')
                if slr.overflow:
                    sheet_info += f'\n\u26a0 {len(slr.overflow)} boards too large for sheet'
            else:
                sheet_info = 'No boards fit on sheet (too small?)'
            self._slicer_sheet_info_var.set(sheet_info)
            self._slicer_sheet_layout = slr
        except (ValueError, AttributeError):
            self._slicer_sheet_layout = None
            try:
                self._slicer_sheet_info_var.set('Enter sheet size to enable layout.')
            except Exception:
                pass

        # Update info panel
        t_mm = result.board_thickness
        plane_name, h_ax, v_ax = _slicer_mod.board_plane_info(axis)
        quality_label = {'fast': 'fast (3 smp, 60²)', 'accurate': 'accurate (7 smp, 120²)'}
        info_lines = [
            f'Boards: {result.n_boards}',
            f'Board thickness: {t_mm:.2f} mm',
            f'Model span ({axis.upper()}): {result.model_span:.1f} mm',
            f'Slice direction: along {axis.upper()}',
            f'Board plane: {plane_name}  ({h_ax} \xd7 {v_ax})',
            f'Profile mode: {slab_mode}',
            f'Quality: {quality_label.get(params["quality"], params["quality"])}',
        ]
        self._slicer_info_var.set('\n'.join(info_lines))

        # Populate listbox + slider
        self._slicer_listbox.delete(0, 'end')
        for s in result.slices:
            self._slicer_listbox.insert('end', s.label)
        n = result.n_boards
        self._slicer_board_slider.config(to=max(n, 1), state='normal' if n > 1 else 'disabled')
        self._slicer_slider_var.set(1)

        # Render previews (status updates inline)
        self.status_label.config(text='Rendering preview…', style='StatusOk.TLabel')
        self.update_idletasks()
        self._slicer_draw_preview(gap=gap)
        self._slicer_draw_3d_preview()

        if MATPLOTLIB_AVAILABLE:
            self._slicer_switch_preview()

        self.status_label.config(
            text=f'Done: {result.n_boards} boards  ({slab_mode}, {params["quality"]})',
            style='StatusOk.TLabel',
        )

    def _slicer_draw_preview(self, gap: float = 20.0,
                              inspect_index: Optional[int] = None) -> None:
        if not MATPLOTLIB_AVAILABLE or self._slicer_result is None:
            return
        ax = self._slicer_ax
        ax.clear()
        ax.set_facecolor('#f9fafc')

        target = self._slicer_result.slices
        if inspect_index is not None:
            if 0 <= inspect_index < len(target):
                target = [target[inspect_index]]
            else:
                self._slicer_canvas_mpl.draw()
                return
        else:
            # Apply step decimation when showing all boards
            step = max(1, getattr(self, '_slicer_step_var', None) and self._slicer_step_var.get() or 1)
            if step > 1:
                target = [sl for i, sl in enumerate(target) if i % step == 0]

        from preview_engine import LAYER_STYLES
        result = self._slicer_result
        stacking_axis = result.stacking_axis
        plane_name, h_axis, v_axis = _slicer_mod.board_plane_info(stacking_axis)

        x_cursor = 0.0
        color_cut = LAYER_STYLES.get('CUT', ('#e53935', 2.0, 'solid'))[0]

        for sl in target:
            if not sl.contours:
                continue
            sorted_c = sorted(sl.contours, key=_slicer_mod._contour_area, reverse=True)
            outer  = sorted_c[0]
            inners = sorted_c[1:]

            xs = [p[0] for p in outer]
            zs = [p[1] for p in outer]
            w  = max(xs) - min(xs)
            x_off = x_cursor - min(xs)

            def _px(c, _xoff=x_off):
                return [p[0] + _xoff for p in c], [p[1] for p in c]

            # Outer CUT profile
            ox, oz = _px(outer)
            ax.plot(ox + [ox[0]], oz + [oz[0]], color=color_cut, lw=1.5)
            ax.fill(ox, oz, alpha=0.08, color=color_cut)

            # Inner features
            for inner in inners:
                area = _slicer_mod._contour_area(inner)
                layer = 'HOLES' if area < 100 else 'TEMPLATE'
                ic = LAYER_STYLES.get(layer, ('#43a047', 1.0, 'solid'))[0]
                ix, iz = _px(inner)
                ax.plot(ix + [ix[0]], iz + [iz[0]], color=ic, lw=1.0)

            # Board label below contour
            cx_label = x_cursor + w / 2
            ax.text(cx_label, min(zs) - 2, sl.label,
                    ha='center', va='top', fontsize=6, color='#555')

            x_cursor += w + gap

        # Title: show the axis and board plane
        n_boards = result.n_boards
        t_mm = result.board_thickness
        if inspect_index is not None:
            title = (f'Board {inspect_index + 1} / {n_boards}  '
                     f'—  slice along {stacking_axis.upper()}  '
                     f'({h_axis}–{v_axis} plane)')
        else:
            title = (f'{n_boards} boards  ·  {t_mm:.1f} mm thick  '
                     f'·  slice along {stacking_axis.upper()}  '
                     f'({h_axis}–{v_axis} plane)')

        ax.set_title(title, fontsize=8, color='#444', pad=4)
        ax.set_xlabel(f'← {h_axis}  (board horizontal) →', fontsize=7, color='#777')
        ax.set_ylabel(f'{v_axis}\n(board\nvertical)', fontsize=7, color='#777', rotation=0,
                      labelpad=28, va='center')
        ax.tick_params(labelsize=6)
        ax.set_aspect('equal')
        # Re-enable axis ticks so coordinates are readable
        ax.axis('on')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)

        self._slicer_fig.tight_layout(pad=1.0)
        self._slicer_canvas_mpl.draw()

    def _slicer_on_select(self, _event) -> None:
        if self._slicer_result is None:
            return
        sel = self._slicer_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        # Sync slider without retriggering on_slider
        self._slicer_slider_var.set(idx + 1)
        self._slicer_render_selection(idx)

    def _slicer_on_slider(self, value) -> None:
        """Board navigation slider changed — sync listbox and update preview."""
        if self._slicer_result is None:
            return
        idx = int(float(value)) - 1
        n   = self._slicer_result.n_boards
        idx = max(0, min(idx, n - 1))
        self._slicer_listbox.selection_clear(0, 'end')
        self._slicer_listbox.selection_set(idx)
        self._slicer_listbox.see(idx)
        self._slicer_render_selection(idx)

    def _slicer_render_selection(self, idx: int) -> None:
        """Re-render the active preview for the given board index."""
        mode = self._slicer_preview_mode.get() if MATPLOTLIB_AVAILABLE else '2d'
        if mode == '3d':
            self._slicer_draw_3d_preview(selected_idx=idx)
        elif mode == 'overlay':
            self._slicer_draw_overlay_preview(highlight_idx=idx)
        else:
            self._slicer_draw_preview(gap=self._slicer_gap_try_float(), inspect_index=idx)

    def _slicer_redraw_current(self) -> None:
        """Redraw the current preview — called by the step spinbox."""
        if self._slicer_result is None:
            return
        mode = self._slicer_preview_mode.get() if MATPLOTLIB_AVAILABLE else '2d'
        if mode == '2d':
            self._slicer_draw_preview(gap=self._slicer_gap_try_float())
        elif mode == 'overlay':
            self._slicer_draw_overlay_preview()

    def _slicer_export_dxf(self) -> None:
        if self._slicer_result is None:
            messagebox.showwarning('Export', 'Run Slice first.')
            return
        path = filedialog.asksaveasfilename(
            defaultextension='.dxf',
            filetypes=[('DXF files', '*.dxf'), ('All files', '*.*')],
            title='Export All Boards — Combined DXF',
            initialdir=OUTPUT_DIR,
        )
        if not path:
            return
        try:
            gap = self._slicer_gap_try_float()
            slr = getattr(self, '_slicer_sheet_layout', None)
            count = _slicer_mod.slices_to_dxf(
                self._slicer_result, path,
                layout_gap=gap,
                sheet_layout_result=slr,
            )
            layout_note = ' (sheet layout)' if slr else ' (linear strip)'
            self.status_label.config(
                text=f'Exported {count} entities{layout_note} → {path}',
                style='StatusOk.TLabel',
            )
        except Exception as exc:
            messagebox.showerror('Export Error', str(exc))

    def _slicer_export_per_board(self) -> None:
        if self._slicer_result is None:
            messagebox.showwarning('Export', 'Run Slice first.')
            return
        import os
        folder = filedialog.askdirectory(
            title='Choose folder for per-board DXF files',
            initialdir=OUTPUT_DIR,
        )
        if not folder:
            return
        try:
            n = self._slicer_result.n_boards
            total = _slicer_mod.slices_to_dxf_per_board(
                self._slicer_result, folder, prefix='board')
            self.status_label.config(
                text=f'Exported {n} boards ({total} entities) to {folder}',
                style='StatusOk.TLabel',
            )
            messagebox.showinfo(
                'Export Complete',
                f'{n} DXF files written to:\n{folder}\n\n'
                f'Files: board_001.dxf … board_{n:03d}.dxf',
            )
        except Exception as exc:
            messagebox.showerror('Export Error', str(exc))

    def _slicer_send_all(self) -> None:
        if self._slicer_result is None:
            messagebox.showwarning('Send to Editor', 'Run Slice first.')
            return
        gap   = self._slicer_gap_try_float()
        ents  = _slicer_mod.slices_to_entities(self._slicer_result, layout_gap=gap)
        self._editor_entities.clear()
        self._editor_entities.extend(ents)
        self.interactive_canvas.set_entities(self._editor_entities)
        self.tab_control.select(self.editor_tab)
        self.status_label.config(
            text=f'Sent {len(ents)} slice entities to editor',
            style='StatusOk.TLabel',
        )

    def _slicer_send_selected(self) -> None:
        if self._slicer_result is None:
            messagebox.showwarning('Send to Editor', 'Run Slice first.')
            return
        sel = self._slicer_listbox.curselection()
        if not sel:
            messagebox.showinfo('Send to Editor', 'Select a board from the list first.')
            return
        idx  = sel[0]
        gap  = self._slicer_gap_try_float()
        ents = _slicer_mod.slices_to_entities(
            self._slicer_result, layout_gap=gap, inspect_index=idx)
        self._editor_entities.clear()
        self._editor_entities.extend(ents)
        self.interactive_canvas.set_entities(self._editor_entities)
        self.tab_control.select(self.editor_tab)
        self.status_label.config(
            text=f'Sent board {idx+1} to editor ({len(ents)} entities)',
            style='StatusOk.TLabel',
        )

    def _slicer_gap_try_float(self) -> float:
        try:
            return float(self._slicer_gap_var.get())
        except (ValueError, AttributeError):
            return 20.0

    def create_project_tab(self):
        """Create the Project Management tab."""
        scroll_outer, _scroll_inner = self._make_scrollable_panel(self.project_tab)
        scroll_outer.pack(fill='both', expand=True)
        main_frame = ttk.Frame(_scroll_inner, padding=12)
        main_frame.pack(fill='x')
        main_frame.columnconfigure(1, weight=1)

        # ===== PROJECT CONTROLS =====
        controls_frame = ttk.Frame(main_frame)
        controls_frame.pack(fill='x', pady=(0, 12))

        # Project name and controls
        project_frame = ttk.Frame(controls_frame)
        project_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(project_frame, text='Project:', font=_FONT_BOLD).pack(side='left')
        self.project_name_var = tk.StringVar(value='Untitled Project')
        project_name_entry = ttk.Entry(project_frame, textvariable=self.project_name_var, width=30)
        project_name_entry.pack(side='left', padx=(8, 8))

        project_buttons = ttk.Frame(project_frame)
        project_buttons.pack(side='left')
        self.new_project_button = ttk.Button(project_buttons, text='New Project', command=self.new_project)
        self.new_project_button.pack(side='left', padx=(0, 4))
        self.save_project_button = ttk.Button(project_buttons, text='Save Project', command=self.save_project)
        self.save_project_button.pack(side='left', padx=(0, 4))
        self.load_project_button = ttk.Button(project_buttons, text='Load Project', command=self.load_project)
        self.load_project_button.pack(side='left')

        # ===== PARTS MANAGEMENT =====
        parts_frame = ttk.LabelFrame(main_frame, text='Parts in Project', padding=10)
        parts_frame.pack(fill='y', side='left', padx=(0, 8))
        parts_frame.rowconfigure(1, weight=1)

        # Parts list
        parts_list_frame = ttk.Frame(parts_frame)
        parts_list_frame.pack(fill='both', expand=True)

        self.parts_listbox = tk.Listbox(parts_list_frame, height=15, exportselection=False, font=_FONT_UI, bg=_CLR_PANEL, relief='flat', bd=0, selectbackground=_CLR_ACCENT, selectforeground='white', highlightthickness=0)
        self.parts_listbox.pack(side='left', fill='both', expand=True)
        parts_scrollbar = ttk.Scrollbar(parts_list_frame, orient='vertical', command=self.parts_listbox.yview)
        parts_scrollbar.pack(side='right', fill='y')
        self.parts_listbox.config(yscrollcommand=parts_scrollbar.set)
        self.parts_listbox.bind('<<ListboxSelect>>', self.on_part_select)

        # Part management buttons
        part_buttons_frame = ttk.Frame(parts_frame)
        part_buttons_frame.pack(fill='x', pady=(8, 0))
        part_buttons_frame.columnconfigure((0, 1), weight=1)

        self.add_part_button = ttk.Button(part_buttons_frame, text='Add Current Part', command=self.add_current_part_to_project)
        self.add_part_button.grid(row=0, column=0, sticky='ew', padx=(0, 4))
        self.remove_part_button = ttk.Button(part_buttons_frame, text='Remove Part', command=self.remove_part_from_project)
        self.remove_part_button.grid(row=0, column=1, sticky='ew', padx=(4, 0))

        # ===== PART EDITOR =====
        editor_frame = ttk.LabelFrame(main_frame, text='Part Editor', padding=10)
        editor_frame.pack(fill='both', expand=True, side='right')
        editor_frame.columnconfigure(0, weight=1)

        # Part name
        part_name_frame = ttk.Frame(editor_frame)
        part_name_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(part_name_frame, text='Part Name:', font=_FONT_BOLD).pack(side='left')
        self.part_name_var = tk.StringVar(value='')
        part_name_entry = ttk.Entry(part_name_frame, textvariable=self.part_name_var)
        part_name_entry.pack(side='left', padx=(8, 0), fill='x', expand=True)

        # Template selection for part
        template_frame = ttk.Frame(editor_frame)
        template_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(template_frame, text='Template:', font=_FONT_BOLD).pack(side='left')
        self.part_template_var = tk.StringVar(value='Rectangle')
        part_template_menu = ttk.OptionMenu(template_frame, self.part_template_var, self.part_template_var.get(),
                                           *TEMPLATES.keys(), command=self.on_part_template_change)
        part_template_menu.pack(side='left', padx=(8, 0), fill='x', expand=True)

        # Part parameters frame
        self.part_params_frame = ttk.LabelFrame(editor_frame, text='Part Parameters', padding=10)
        self.part_params_frame.pack(fill='both', expand=True, pady=(0, 8))
        self.part_params_frame.columnconfigure((0, 2), weight=1)

        # Part action buttons
        part_action_frame = ttk.Frame(editor_frame)
        part_action_frame.pack(fill='x')
        part_action_frame.columnconfigure((0, 1), weight=1)

        self.update_part_button = ttk.Button(part_action_frame, text='Update Part', command=self.update_current_part)
        self.update_part_button.grid(row=0, column=0, sticky='ew', padx=(0, 4))
        self.generate_part_dxf_button = ttk.Button(part_action_frame, text='Generate Part DXF', command=self.generate_part_dxf)
        self.generate_part_dxf_button.grid(row=0, column=1, sticky='ew', padx=(4, 0))

        # ===== PROJECT ACTIONS =====
        project_actions_frame = ttk.LabelFrame(main_frame, text='Project Actions', padding=10)
        project_actions_frame.pack(fill='x', pady=(8, 0))
        project_actions_frame.columnconfigure((0, 1, 2), weight=1)

        self.nest_all_parts_button = ttk.Button(project_actions_frame, text='Nest All Parts', command=self.nest_all_parts)
        self.nest_all_parts_button.grid(row=0, column=0, sticky='ew', padx=(0, 4))
        self.generate_all_dxfs_button = ttk.Button(project_actions_frame, text='Generate All DXFs', command=self.generate_all_parts_dxf)
        self.generate_all_dxfs_button.grid(row=0, column=1, sticky='ew', padx=(0, 4))
        self.export_combined_layout_button = ttk.Button(project_actions_frame, text='Export Combined Layout', command=self.export_combined_layout)
        self.export_combined_layout_button.grid(row=0, column=2, sticky='ew', padx=(4, 0))

        # Initialize part editor
        self.part_field_vars = {}
        self.render_part_fields()

    def create_nesting_tab(self):
        """Create the Material Optimization tab."""
        scroll_outer, _scroll_inner = self._make_scrollable_panel(self.nesting_tab)
        scroll_outer.pack(fill='both', expand=True)
        main_frame = ttk.Frame(_scroll_inner, padding=12)
        main_frame.pack(fill='x')
        main_frame.columnconfigure(0, weight=1)

        # ===== INPUT SECTION =====
        input_frame = ttk.LabelFrame(main_frame, text='Nesting Parameters', padding=10)
        input_frame.pack(fill='x', pady=(0, 12))
        input_frame.columnconfigure((0, 2), weight=1)

        # Template selection
        template_frame = ttk.Frame(input_frame)
        template_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(template_frame, text='Part Template', font=_FONT_BOLD).pack(side='left')
        nesting_template_menu = ttk.OptionMenu(template_frame, self.nesting_template_var,
                                              self.nesting_template_var.get(), *TEMPLATES.keys(),
                                              command=self.on_nesting_template_change)
        nesting_template_menu.pack(side='left', padx=(8, 0), fill='x', expand=True)

        # Sheet dimensions
        sheet_frame = ttk.Frame(input_frame)
        sheet_frame.pack(fill='x', pady=(0, 8))
        sheet_frame.columnconfigure((0, 2), weight=1)

        ttk.Label(sheet_frame, text='Sheet Width (mm)').grid(row=0, column=0, sticky='w', pady=6, padx=(0, 8))
        sheet_width_entry = ttk.Entry(sheet_frame, textvariable=self.sheet_width_var)
        sheet_width_entry.grid(row=0, column=1, sticky='ew', pady=6)

        ttk.Label(sheet_frame, text='Sheet Height (mm)').grid(row=0, column=2, sticky='w', pady=6, padx=(8, 8))
        sheet_height_entry = ttk.Entry(sheet_frame, textvariable=self.sheet_height_var)
        sheet_height_entry.grid(row=0, column=3, sticky='ew', pady=6)

        # Part count
        count_frame = ttk.Frame(input_frame)
        count_frame.pack(fill='x', pady=(0, 8))
        ttk.Label(count_frame, text='Number of Parts').pack(side='left')
        part_count_entry = ttk.Entry(count_frame, textvariable=self.part_count_var, width=10)
        part_count_entry.pack(side='left', padx=(8, 0))

        # ===== PART PARAMETERS SECTION =====
        self.nesting_shape_frame = ttk.LabelFrame(main_frame, text='Part Parameters', padding=10)
        self.nesting_shape_frame.pack(fill='x', pady=(0, 8))
        self.nesting_shape_frame.columnconfigure((0, 2), weight=1)
        self.nesting_fields_frame = self.nesting_shape_frame

        # ===== ACTION BUTTONS =====
        nesting_button_frame = ttk.Frame(main_frame)
        nesting_button_frame.pack(fill='x', pady=(16, 12))
        nesting_button_frame.columnconfigure((0, 1), weight=1)

        self.optimize_button = ttk.Button(nesting_button_frame, text='Optimize Nesting', command=self.on_optimize_nesting)
        self.optimize_button.grid(row=0, column=0, sticky='ew', padx=(0, 4))

        self.nesting_preview_button = ttk.Button(nesting_button_frame, text='Preview Layout', command=self.on_preview_nesting)
        self.nesting_preview_button.grid(row=0, column=1, sticky='ew', padx=(4, 0))

        # ===== RESULTS SECTION =====
        results_frame = ttk.LabelFrame(main_frame, text='Optimization Results', padding=10)
        results_frame.pack(fill='x', pady=(0, 12))

        self.results_text = tk.Text(results_frame, width=60, height=6, wrap='word', state='disabled', bg=_CLR_PANEL, relief='flat', bd=1, highlightthickness=1, highlightbackground=_CLR_BORDER, font=_FONT_UI)
        self.results_text.pack(fill='x')

        # ===== SMART SUGGESTIONS SECTION =====
        suggestions_frame = ttk.LabelFrame(main_frame, text='Smart Suggestions', padding=10)
        suggestions_frame.pack(fill='x', pady=(0, 12))

        self.suggestions_text = tk.Text(suggestions_frame, width=60, height=5, wrap='word', state='disabled', bg=_CLR_PANEL, relief='flat', bd=1, highlightthickness=1, highlightbackground=_CLR_BORDER, font=_FONT_UI)
        self.suggestions_text.pack(fill='x')

        # ===== NESTING PREVIEW SECTION =====
        self.nesting_preview_frame = ttk.LabelFrame(main_frame, text='Nesting Layout Preview', padding=10)
        self.nesting_preview_frame.pack(fill='both', expand=True, pady=(0, 12))

        if MATPLOTLIB_AVAILABLE:
            # Create matplotlib figure and canvas for nesting
            self.nesting_fig = Figure(figsize=(8, 6), dpi=100)
            self.nesting_ax = self.nesting_fig.add_subplot(111)
            self.nesting_canvas = FigureCanvasTkAgg(self.nesting_fig, master=self.nesting_preview_frame)
            self.nesting_canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            ttk.Label(self.nesting_preview_frame, text='Matplotlib not available for nesting preview').pack(pady=20)

        # Initialize nesting fields
        self.render_nesting_fields()

    def create_photo_to_dxf_tab(self):
        """Create the Photo-to-DXF tab."""
        if not OPENCV_AVAILABLE:
            # Show error message if OpenCV is not available
            main_frame = ttk.Frame(self.photo_tab, padding=12)
            main_frame.pack(fill='both', expand=True)
            ttk.Label(main_frame, text='Photo-to-DXF requires OpenCV and PIL/Pillow.\nPlease install with: pip install opencv-python pillow',
                     font=_FONT_TITLE).pack(pady=50)
            return

        scroll_outer, _scroll_inner = self._make_scrollable_panel(self.photo_tab)
        scroll_outer.pack(fill='both', expand=True)
        main_frame = ttk.Frame(_scroll_inner, padding=12)
        main_frame.pack(fill='x')
        main_frame.columnconfigure(1, weight=1)

        # ===== IMAGE INPUT SECTION =====
        input_frame = ttk.LabelFrame(main_frame, text='Image Input', padding=10)
        input_frame.pack(fill='x', pady=(0, 12))

        input_button_frame = ttk.Frame(input_frame)
        input_button_frame.pack(fill='x', pady=(0, 8))
        self.load_image_button = ttk.Button(input_button_frame, text='Load Image', command=self.load_image)
        self.load_image_button.pack(side='left')

        # ===== PARAMETERS SECTION =====
        params_frame = ttk.LabelFrame(main_frame, text='Processing Parameters', padding=10)
        params_frame.pack(fill='x', pady=(0, 12))
        params_frame.columnconfigure((0, 2, 4), weight=1)

        # Edge detection parameters
        ttk.Label(params_frame, text='Edge Detection').grid(row=0, column=0, sticky='w', pady=6, padx=(0, 8))
        ttk.Label(params_frame, text='Threshold 1').grid(row=1, column=0, sticky='w', pady=6, padx=(0, 8))
        threshold1_entry = ttk.Entry(params_frame, textvariable=self.photo_threshold1_var, width=8)
        threshold1_entry.grid(row=1, column=1, sticky='ew', pady=6)

        ttk.Label(params_frame, text='Threshold 2').grid(row=2, column=0, sticky='w', pady=6, padx=(0, 8))
        threshold2_entry = ttk.Entry(params_frame, textvariable=self.photo_threshold2_var, width=8)
        threshold2_entry.grid(row=2, column=1, sticky='ew', pady=6)

        # Contour filtering
        ttk.Label(params_frame, text='Contour Filtering').grid(row=0, column=2, sticky='w', pady=6, padx=(16, 8))
        ttk.Label(params_frame, text='Min Contour Length').grid(row=1, column=2, sticky='w', pady=6, padx=(16, 8))
        min_contour_entry = ttk.Entry(params_frame, textvariable=self.photo_min_contour_var, width=8)
        min_contour_entry.grid(row=1, column=3, sticky='ew', pady=6)

        # Geometry simplification
        ttk.Label(params_frame, text='Simplification').grid(row=0, column=4, sticky='w', pady=6, padx=(16, 8))
        ttk.Label(params_frame, text='Smoothing (epsilon)').grid(row=1, column=4, sticky='w', pady=6, padx=(16, 8))
        smoothing_entry = ttk.Entry(params_frame, textvariable=self.photo_smoothing_var, width=8)
        smoothing_entry.grid(row=1, column=5, sticky='ew', pady=6)

        # ===== SCALING SECTION =====
        scale_frame = ttk.LabelFrame(main_frame, text='Output Scaling', padding=10)
        scale_frame.pack(fill='x', pady=(0, 12))
        scale_frame.columnconfigure((0, 2), weight=1)

        ttk.Label(scale_frame, text='Scale Factor').grid(row=0, column=0, sticky='w', pady=6, padx=(0, 8))
        scale_entry = ttk.Entry(scale_frame, textvariable=self.photo_scale_var, width=10)
        scale_entry.grid(row=0, column=1, sticky='ew', pady=6)

        ttk.Label(scale_frame, text='OR Target Size (mm)').grid(row=0, column=2, sticky='w', pady=6, padx=(16, 8))
        ttk.Label(scale_frame, text='Width').grid(row=1, column=2, sticky='w', pady=6, padx=(16, 8))
        width_entry = ttk.Entry(scale_frame, textvariable=self.photo_target_width_var, width=8)
        width_entry.grid(row=1, column=3, sticky='ew', pady=6)

        ttk.Label(scale_frame, text='Height').grid(row=2, column=2, sticky='w', pady=6, padx=(16, 8))
        height_entry = ttk.Entry(scale_frame, textvariable=self.photo_target_height_var, width=8)
        height_entry.grid(row=2, column=3, sticky='ew', pady=6)

        # ===== SMART GEOMETRY RECOGNITION =====
        self.smart_geom_frame = ttk.LabelFrame(main_frame, text='Smart Geometry Recognition', padding=10)
        self.smart_geom_frame.pack(fill='x', pady=(0, 12))

        # Main enable checkbox
        self.smart_geom_checkbox = ttk.Checkbutton(self.smart_geom_frame, text='Enable Smart Geometry Recognition',
                                                  variable=self.photo_smart_geom_enabled,
                                                  command=self.on_smart_geom_toggle)
        self.smart_geom_checkbox.pack(anchor='w', pady=(0, 8))

        # Sub-options frame (initially hidden)
        self.smart_geom_options_frame = ttk.Frame(self.smart_geom_frame)

        # Create sub-options
        options_left = ttk.Frame(self.smart_geom_options_frame)
        options_left.pack(side='left', fill='x', expand=True, padx=(20, 10))

        self.detect_lines_cb = ttk.Checkbutton(options_left, text='Detect straight lines',
                                              variable=self.photo_detect_lines)
        self.detect_lines_cb.pack(anchor='w', pady=2)

        self.detect_circles_cb = ttk.Checkbutton(options_left, text='Detect circles',
                                                variable=self.photo_detect_circles)
        self.detect_circles_cb.pack(anchor='w', pady=2)

        self.detect_rectangles_cb = ttk.Checkbutton(options_left, text='Detect rectangles',
                                                   variable=self.photo_detect_rectangles)
        self.detect_rectangles_cb.pack(anchor='w', pady=2)

        options_right = ttk.Frame(self.smart_geom_options_frame)
        options_right.pack(side='right', fill='x', expand=True, padx=(10, 0))

        self.merge_collinear_cb = ttk.Checkbutton(options_right, text='Merge nearly collinear segments',
                                                 variable=self.photo_merge_collinear)
        self.merge_collinear_cb.pack(anchor='w', pady=2)

        self.remove_tiny_cb = ttk.Checkbutton(options_right, text='Remove tiny segments',
                                             variable=self.photo_remove_tiny)
        self.remove_tiny_cb.pack(anchor='w', pady=2)

        # Initially hide sub-options
        self.on_smart_geom_toggle()

        # ===== ACTION BUTTONS =====
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill='x', pady=(0, 12))
        button_frame.columnconfigure((0, 1, 2), weight=1)

        self.process_image_button = ttk.Button(button_frame, text='Process Image', command=self.process_image)
        self.process_image_button.grid(row=0, column=0, sticky='ew', padx=(0, 4))

        self.generate_photo_dxf_button = ttk.Button(button_frame, text='Generate DXF', command=self.generate_photo_dxf)
        self.generate_photo_dxf_button.grid(row=0, column=1, sticky='ew', padx=(0, 4))

        self.clear_image_button = ttk.Button(button_frame, text='Clear', command=self.clear_image)
        self.clear_image_button.grid(row=0, column=2, sticky='ew', padx=(4, 0))

        # Send to Editor row
        send_frame = ttk.Frame(main_frame)
        send_frame.pack(fill='x', pady=(0, 4))
        ttk.Button(send_frame, text='Send to Editor ›', style='Secondary.TButton',
                   command=self._photo_send_to_editor).pack(side='left')
        ttk.Label(send_frame, text='  Sends processed contours to the Interactive Editor',
                  foreground='gray').pack(side='left')

        # ===== PREVIEW CONTROLS =====
        preview_controls_frame = ttk.Frame(main_frame)
        preview_controls_frame.pack(fill='x', pady=(0, 8))

        ttk.Label(preview_controls_frame, text='Preview Mode:', font=_FONT_BOLD).pack(side='left')
        preview_modes = [('Original', 'original'), ('Edges', 'edges'), ('Contours', 'contours')]
        for text, mode in preview_modes:
            rb = ttk.Radiobutton(preview_controls_frame, text=text, variable=self.photo_preview_mode,
                                value=mode, command=self.update_photo_preview)
            rb.pack(side='left', padx=(8, 0))

        # ===== IMAGE PREVIEW SECTION =====
        self.photo_preview_frame = ttk.LabelFrame(main_frame, text='Image Preview', padding=10)
        self.photo_preview_frame.pack(fill='both', expand=True)

        if MATPLOTLIB_AVAILABLE:
            # Create matplotlib figure and canvas for photo preview
            self.photo_fig = Figure(figsize=(8, 6), dpi=100)
            self.photo_ax = self.photo_fig.add_subplot(111)
            self.photo_canvas = FigureCanvasTkAgg(self.photo_fig, master=self.photo_preview_frame)
            self.photo_canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            ttk.Label(self.photo_preview_frame, text='Matplotlib not available for image preview').pack(pady=20)

    def on_smart_geom_toggle(self):
        """Show/hide smart geometry recognition sub-options."""
        if self.photo_smart_geom_enabled.get():
            self.smart_geom_options_frame.pack(fill='x', pady=(8, 0))
        else:
            self.smart_geom_options_frame.pack_forget()

    def _on_dxf_canvas_configure(self, event):
        """Update inner frame width and scroll region when the left pane canvas resizes."""
        self.dxf_canvas.itemconfig(self._left_window_id, width=event.width)
        self.dxf_canvas.update_idletasks()
        bb = self.dxf_canvas.bbox('all')
        if bb:
            self.dxf_canvas.configure(scrollregion=bb)

    def _on_dxf_inner_configure(self, event=None):
        """Update scroll region when the inner scrollable frame changes size."""
        self.dxf_canvas.update_idletasks()
        bb = self.dxf_canvas.bbox('all')
        if bb:
            self.dxf_canvas.configure(scrollregion=bb)

    # ── Scroll helpers ────────────────────────────────────────────────────────

    def _make_scrollable_panel(self, parent, width=None):
        """
        Create a scrollable content panel inside *parent*.

        If *width* is given the outer frame is pinned to that pixel width
        (useful for fixed-width left-column panels).  Otherwise the outer
        frame fills its parent.

        Returns ``(outer_frame, inner_frame)``.  The caller should
        pack/grid *outer_frame*; all tab content goes into *inner_frame*.
        """
        outer = ttk.Frame(parent)
        if width is not None:
            outer.configure(width=width)
            outer.pack_propagate(False)

        canvas = tk.Canvas(outer, highlightthickness=0, background=_CLR_BG, bd=0)
        scrollbar = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)

        inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        def _refresh(event=None):
            canvas.update_idletasks()
            bb = canvas.bbox('all')
            if bb:
                canvas.configure(scrollregion=bb)

        def _on_canvas_resize(event):
            canvas.itemconfig(window_id, width=event.width)
            _refresh()

        inner.bind('<Configure>', _refresh)
        canvas.bind('<Configure>', _on_canvas_resize)

        # Register so _on_root_mousewheel can find this canvas by walking the
        # master chain from whichever widget the cursor is over.
        self._scroll_canvas_set.add(canvas)
        return outer, inner

    def _on_root_mousewheel(self, event):
        """Route mousewheel to whichever registered scroll canvas is under the cursor."""
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget in self._scroll_canvas_set:
                widget.yview_scroll(int(-1 * (event.delta / 120)), 'units')
                return
            try:
                widget = widget.master
            except AttributeError:
                break

    def _on_root_linux_scroll(self, event):
        """Linux Button-4/5 equivalent of _on_root_mousewheel."""
        delta = -1 if event.num == 4 else 1
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget in self._scroll_canvas_set:
                widget.yview_scroll(delta, 'units')
                return
            try:
                widget = widget.master
            except AttributeError:
                break

    def on_nesting_template_change(self, event=None):
        self.render_nesting_fields()

    def render_nesting_fields(self):
        """Render the parameter fields for the selected nesting template."""
        # Clear existing fields
        for child in self.nesting_shape_frame.winfo_children():
            child.destroy()

        template = TEMPLATES[self.nesting_template_var.get()]

        # Render shape parameters
        shape_row = 0
        col = 0
        for idx, (label_text, field_name) in enumerate(template['fields']):
            # 2-column layout
            if idx % 2 == 0:
                col = 0
            else:
                col = 2
                shape_row += 1

            ttk.Label(self.nesting_shape_frame, text=label_text).grid(row=shape_row, column=col, sticky='w', pady=6, padx=(0, 8))
            var = tk.StringVar(value=self.nesting_field_vars.get(field_name, ''))
            entry = ttk.Entry(self.nesting_shape_frame, textvariable=var)
            entry.grid(row=shape_row, column=col+1, sticky='ew', pady=6)
            self.nesting_field_vars[field_name] = var

    def _update_dxf_scroll_region(self):
        """Update the DXF canvas scroll region."""
        self.dxf_canvas.update_idletasks()
        bb = self.dxf_canvas.bbox('all')
        if bb:
            self.dxf_canvas.configure(scrollregion=bb)

    def on_optimize_nesting(self):
        """Run the nesting optimization."""
        try:
            template_name = self.nesting_template_var.get()

            # Get parameters
            params = {}
            for name, var in self.nesting_field_vars.items():
                value = var.get().strip()
                if not value:
                    value = _PREVIEW_DEFAULTS.get(name)
                    if value is None:
                        continue
                params[name] = value

            sheet_width = float(self.sheet_width_var.get())
            sheet_height = float(self.sheet_height_var.get())
            part_count = int(self.part_count_var.get())

            # Run optimization
            self.nesting_results = optimize_nesting(
                template_name, params, sheet_width, sheet_height, part_count
            )

            # Display results
            self.display_nesting_results()

            # Update preview
            self.update_nesting_preview()

        except Exception as exc:
            messagebox.showerror('Nesting Error', f'Failed to optimize nesting: {exc}')

    def display_nesting_results(self):
        """Display the nesting optimization results."""
        if not self.nesting_results:
            return

        results = self.nesting_results
        lines = [
            f'Total parts to place: {results["total_parts_placed"]}',
            f'Sheets required: {results["total_sheets_used"]}',
            f'Parts per sheet: {results["parts_per_sheet"]:.1f}',
            f'Average utilization: {results["average_utilization"]:.1f}%',
            f'Total waste: {results["total_waste_area"]:.1f} mm² ({results["waste_percentage"]:.1f}%)',
            f'Total material used: {results["total_material_used"]:.1f} mm²'
        ]

        if 'best_orientation' in results:
            lines.append(f'Best orientation: {results["best_orientation"]}°')

        if results.get('layout_comparisons'):
            lines.append('Orientation comparison:')
            for option in results['layout_comparisons']:
                lines.append(
                    f'  {option["orientation"]}° → {option["count"]} parts per sheet, {option["utilization"]:.1f}% utilization'
                )

        if results.get('suggestions'):
            lines.append('')
            lines.append('Smart suggestions:')
            for suggestion in results['suggestions']:
                lines.append(f'  - {suggestion}')

        self.results_text.config(state='normal')
        self.results_text.delete('1.0', tk.END)
        self.results_text.insert(tk.END, '\n'.join(lines))
        self.results_text.config(state='disabled')

        self.suggestions_text.config(state='normal')
        self.suggestions_text.delete('1.0', tk.END)
        if results.get('suggestions'):
            self.suggestions_text.insert(tk.END, '\n'.join(results['suggestions']))
        else:
            self.suggestions_text.insert(tk.END, 'No suggestions available. Run optimization to see improvement tips.')
        self.suggestions_text.config(state='disabled')

    def update_nesting_preview(self):
        """Update the nesting layout preview."""
        if not MATPLOTLIB_AVAILABLE or not self.nesting_results:
            return

        # Clear previous plot
        self.nesting_ax.clear()

        sheets = self.nesting_results['sheets']
        if not sheets:
            self.nesting_ax.set_title('No sheets to display')
            self.nesting_canvas.draw()
            return

        # For now, show the first sheet. In a more advanced version, we could show all sheets
        sheet = sheets[0]

        # Draw sheet outline
        sheet_rect = plt.Rectangle((0, 0), sheet.width, sheet.height,
                                 fill=False, edgecolor='black', linewidth=2, label='Sheet')
        self.nesting_ax.add_patch(sheet_rect)

        # Draw placed parts
        colors = ['red', 'blue', 'green', 'orange', 'purple', 'brown', 'pink', 'gray', 'olive', 'cyan']
        for i, part in enumerate(sheet.parts):
            color = colors[i % len(colors)]
            width, height = part.get_current_dimensions()

            part_rect = plt.Rectangle((part.x, part.y), width, height,
                                    fill=True, facecolor=color, alpha=0.7,
                                    edgecolor='black', linewidth=1,
                                    label=f'{part.name} ({part.rotation}°)')
            self.nesting_ax.add_patch(part_rect)

            # Add part label
            self.nesting_ax.text(part.x + width/2, part.y + height/2,
                               f'{i+1}', ha='center', va='center',
                               fontsize=8, fontweight='bold')

        # Set equal aspect ratio
        self.nesting_ax.set_aspect('equal', adjustable='datalim')

        # Add grid
        self.nesting_ax.grid(True, which='both', color='lightgray', linestyle='-', linewidth=0.3, alpha=0.5)
        self.nesting_ax.set_axisbelow(True)

        # Set labels and title
        self.nesting_ax.set_xlabel('X (mm)')
        self.nesting_ax.set_ylabel('Y (mm)')
        self.nesting_ax.set_title(f'Nesting Layout - Sheet 1/{len(sheets)} (Utilization: {sheet.get_utilization_percentage():.1f}%)')

        # Set margins
        margin = max(sheet.width, sheet.height) * 0.05
        self.nesting_ax.set_xlim(-margin, sheet.width + margin)
        self.nesting_ax.set_ylim(-margin, sheet.height + margin)

        # Add legend
        handles, labels = self.nesting_ax.get_legend_handles_labels()
        if handles:
            self.nesting_ax.legend(loc='upper right', fontsize=8, framealpha=0.9)

        # Redraw the canvas
        self.nesting_canvas.draw()

    def on_preview_nesting(self):
        """Preview the nesting layout in a separate window."""
        if not MATPLOTLIB_AVAILABLE or not self.nesting_results:
            messagebox.showinfo('Preview', 'Run optimization first to generate preview.')
            return

        import matplotlib.pyplot as plt

        sheets = self.nesting_results['sheets']
        if not sheets:
            messagebox.showinfo('Preview', 'No sheets to preview.')
            return

        # Create figure with subplots for each sheet
        fig, axes = plt.subplots(1, len(sheets), figsize=(6*len(sheets), 6))
        if len(sheets) == 1:
            axes = [axes]

        colors = ['red', 'blue', 'green', 'orange', 'purple', 'brown', 'pink', 'gray', 'olive', 'cyan']

        for sheet_idx, (sheet, ax) in enumerate(zip(sheets, axes)):
            # Draw sheet outline
            sheet_rect = plt.Rectangle((0, 0), sheet.width, sheet.height,
                                     fill=False, edgecolor='black', linewidth=2)
            ax.add_patch(sheet_rect)

            # Draw placed parts
            for i, part in enumerate(sheet.parts):
                color = colors[i % len(colors)]
                width, height = part.get_current_dimensions()

                part_rect = plt.Rectangle((part.x, part.y), width, height,
                                        fill=True, facecolor=color, alpha=0.7,
                                        edgecolor='black', linewidth=1)
                ax.add_patch(part_rect)

                # Add part label
                ax.text(part.x + width/2, part.y + height/2,
                       f'{i+1}', ha='center', va='center',
                       fontsize=8, fontweight='bold')

            # Set equal aspect ratio
            ax.set_aspect('equal', adjustable='datalim')

            # Add grid
            ax.grid(True, which='both', color='lightgray', linestyle='-', linewidth=0.3, alpha=0.5)
            ax.set_axisbelow(True)

            # Set labels and title
            ax.set_xlabel('X (mm)')
            ax.set_ylabel('Y (mm)')
            ax.set_title(f'Sheet {sheet_idx+1} (Utilization: {sheet.get_utilization_percentage():.1f}%)')

            # Set margins
            margin = max(sheet.width, sheet.height) * 0.05
            ax.set_xlim(-margin, sheet.width + margin)
            ax.set_ylim(-margin, sheet.height + margin)

        plt.tight_layout()
        plt.show()

    def _update_scroll_region(self):
        """Update the DXF canvas scroll region (kept for backward compatibility)."""
        self._update_dxf_scroll_region()

    def on_template_change(self, event=None):
        self.render_fields()
        self.schedule_preview_update()

    def on_flange_toggle(self):
        self.render_fields()
        self.schedule_preview_update()

    def on_pattern_toggle(self):
        self.render_fields()
        self.schedule_preview_update()

    def render_fields(self):
        # Store existing values before clearing
        existing_values = {}
        for name, var in self.field_vars.items():
            existing_values[name] = var.get()

        # Clear all section frames
        for child in self.shape_frame.winfo_children():
            child.destroy()
        for child in self.flange_section_frame.winfo_children():
            child.destroy()
        for child in self.pattern_section_frame.winfo_children():
            child.destroy()
        self.entry_widgets.clear()

        template = TEMPLATES[self.template_var.get()]

        # ===== SHAPE PARAMETERS =====
        shape_row = 0
        col = 0
        for idx, (label_text, field_name) in enumerate(template['fields']):
            # 2-column layout
            if idx % 2 == 0:
                col = 0
            else:
                col = 2
                shape_row += 1

            ttk.Label(self.shape_frame, text=label_text).grid(row=shape_row, column=col, sticky='w', pady=6, padx=(0, 8))
            var = tk.StringVar(value=existing_values.get(field_name, ''))
            entry = ttk.Entry(self.shape_frame, textvariable=var)
            entry.grid(row=shape_row, column=col+1, sticky='ew', pady=6)
            self.field_vars[field_name] = var
            self.entry_widgets.append(entry)
            # Bind live preview update
            var.trace_add('write', self.on_field_change)

        # ===== FLANGE SECTION =====
        if self.flange_enabled.get():
            # Show flange frame if hidden
            if not self.flange_section_frame.winfo_viewable():
                self.flange_section_frame.pack(fill='x', pady=(0, 8))

            flange_row = 0
            col = 0
            for idx, (label_text, field_name) in enumerate(FLANGE_FIELDS):
                # 2-column layout
                if idx % 2 == 0:
                    col = 0
                else:
                    col = 2
                    flange_row += 1

                ttk.Label(self.flange_section_frame, text=label_text).grid(row=flange_row, column=col, sticky='w', pady=6, padx=(0, 8))
                var = tk.StringVar(value=existing_values.get(field_name, ''))
                entry = ttk.Entry(self.flange_section_frame, textvariable=var)
                entry.grid(row=flange_row, column=col+1, sticky='ew', pady=6)
                self.field_vars[field_name] = var
                self.entry_widgets.append(entry)
                # Bind live preview update
                var.trace_add('write', self.on_field_change)
        else:
            # Hide flange frame if shown
            self.flange_section_frame.pack_forget()

        # ===== PATTERN SECTION =====
        if self.pattern_enabled.get():
            # Show pattern frame if hidden
            if not self.pattern_section_frame.winfo_viewable():
                self.pattern_section_frame.pack(fill='x', pady=(0, 8))

            pattern_row = 0
            col = 0

            # Pattern type dropdown
            ttk.Label(self.pattern_section_frame, text='Pattern Type').grid(row=pattern_row, column=0, sticky='w', pady=6, padx=(0, 8))
            pattern_types = ['circles', 'squares', 'triangles']
            pattern_menu = ttk.OptionMenu(self.pattern_section_frame, self.pattern_type_var, self.pattern_type_var.get(), *pattern_types)
            pattern_menu.grid(row=pattern_row, column=1, sticky='ew', pady=6)
            # Bind live preview update to pattern type
            self.pattern_type_var.trace_add('write', self.on_field_change)
            pattern_row += 1

            # Pattern parameter fields in 2-column layout
            col = 0
            for idx, (label_text, field_name) in enumerate(PATTERN_FIELDS):
                # 2-column layout
                if idx % 2 == 0:
                    col = 0
                else:
                    col = 2
                    pattern_row += 1

                ttk.Label(self.pattern_section_frame, text=label_text).grid(row=pattern_row, column=col, sticky='w', pady=6, padx=(0, 8))
                var = tk.StringVar(value=existing_values.get(field_name, '10' if 'size' in field_name else '20' if 'spacing' in field_name else '5'))
                entry = ttk.Entry(self.pattern_section_frame, textvariable=var)
                entry.grid(row=pattern_row, column=col+1, sticky='ew', pady=6)
                self.field_vars[field_name] = var
                self.entry_widgets.append(entry)
                # Bind live preview update
                var.trace_add('write', self.on_field_change)
        else:
            # Hide pattern frame if shown
            self.pattern_section_frame.pack_forget()

        # ===== CORNER RELIEF SECTION =====
        # Show for flat-pattern templates always; for Rectangle only when flanges enabled
        _flat_templates = {'Box Flat Pattern', 'L Bracket Flat Pattern', 'Channel Flat Pattern'}
        template_name = self.template_var.get()
        show_relief = template_name in _flat_templates or (
            template_name == 'Rectangle' and self.flange_enabled.get()
        )
        if show_relief:
            self.relief_frame.pack(fill='x', pady=(0, 8))
        else:
            self.relief_frame.pack_forget()

        # Set up keyboard navigation
        self.setup_keyboard_navigation()

        # Update scroll region after adding/removing fields
        self.after(50, self._update_dxf_scroll_region)

    def setup_keyboard_navigation(self):
        """Set up keyboard navigation for entry fields."""
        for i, entry in enumerate(self.entry_widgets):
            # Bind Enter key to move to next field
            entry.bind('<Return>', lambda e, idx=i: self.focus_next_field(idx))
            entry.bind('<KP_Enter>', lambda e, idx=i: self.focus_next_field(idx))

            # Bind Up/Down arrows to navigate between fields
            entry.bind('<Up>', lambda e, idx=i: self.focus_prev_field(idx))
            entry.bind('<Down>', lambda e, idx=i: self.focus_next_field(idx))

    def focus_next_field(self, current_index):
        """Move focus to the next field."""
        next_index = (current_index + 1) % len(self.entry_widgets)
        self.entry_widgets[next_index].focus_set()
        self.entry_widgets[next_index].select_range(0, tk.END)

    def focus_prev_field(self, current_index):
        """Move focus to the previous field."""
        prev_index = (current_index - 1) % len(self.entry_widgets)
        self.entry_widgets[prev_index].focus_set()
        self.entry_widgets[prev_index].select_range(0, tk.END)

    # ── Parameter collection ─────────────────────────────────────────────────
    #
    # Single authoritative place for reading form state into a params dict.
    # Two modes:
    #   _collect_params()        – for preview/analysis: falls back to defaults
    #                              so a partially-filled form still renders.
    #   _collect_strict_params() – for generation: raises on any blank field.

    def _collect_params(self) -> Dict:
        """Collect current form values, substituting defaults for blank fields."""
        params: Dict = {}
        for name, var in self.field_vars.items():
            value = var.get().strip()
            if not value:
                value = _PREVIEW_DEFAULTS.get(name)
                if value is None:
                    continue
            params[name] = value

        params['pattern_enabled'] = self.pattern_enabled.get()
        if self.pattern_enabled.get():
            params['pattern_type'] = self.pattern_type_var.get()

        params['relief_type'] = self.relief_type_var.get()
        params['relief_size'] = self.relief_size_var.get() or '3.0'
        return params

    def _collect_strict_params(self) -> Dict:
        """Collect current form values; raises ValueError on any blank field."""
        params: Dict = {}
        for name, var in self.field_vars.items():
            value = var.get().strip()
            if not value:
                raise ValueError(f'Enter {name.replace("_", " ")}.')
            params[name] = value

        params['pattern_enabled'] = self.pattern_enabled.get()
        if self.pattern_enabled.get():
            params['pattern_type'] = self.pattern_type_var.get()

        params['relief_type'] = self.relief_type_var.get()
        params['relief_size'] = self.relief_size_var.get() or '3.0'
        return params

    # ── Generation ───────────────────────────────────────────────────────────

    def on_generate(self):
        """Validate fields, write DXF to disk, update status and metadata."""
        template_name = self.template_var.get()
        try:
            params = self._collect_strict_params()
            safe_name = template_name.lower().replace(' ', '_')
            output_path = os.path.join(OUTPUT_DIR, f'{safe_name}.dxf')
            _generate_dxf_file(template_name, params, output_path)
            self.last_output_path = output_path
            self.status_label.config(text=f'Created: {output_path}',
                                     style='StatusOk.TLabel')
            self._update_metadata(template_name, params)
        except Exception as exc:
            messagebox.showerror('Error', str(exc))
            self.status_label.config(text='Generation failed',
                                     style='StatusErr.TLabel')

    def _update_metadata(self, template_name: str, params: Dict) -> None:
        """Write a compact param summary into the metadata text widget."""
        _skip = {'pattern_enabled', 'pattern_type', 'relief_type', 'relief_size'}
        lines = [f'{template_name}   {datetime.now().strftime("%H:%M:%S")}']
        for name, value in params.items():
            if name in _skip:
                continue
            lines.append(f'{name.replace("_", " ").title()}: {value} mm')
        self.metadata_text.config(state='normal')
        self.metadata_text.delete('1.0', tk.END)
        self.metadata_text.insert(tk.END, '\n'.join(lines))
        self.metadata_text.config(state='disabled')

    # ── Preview pipeline: params → entities → render ─────────────────────────
    #
    # Flow:
    #   schedule_preview_update()        debounce trigger (field change / toggle)
    #     └─ update_live_preview()       collects params, generates entities,
    #                                    runs analysis, renders — once, no loops
    #
    # analyze_fabrication() is called only from update_live_preview(), receiving
    # already-generated entities.  It updates self.fabrication_issues and the
    # warnings panel; it never triggers any rendering.

    def schedule_preview_update(self):
        """Debounce: cancel any pending preview and schedule a new one."""
        if self.preview_after_id:
            self.after_cancel(self.preview_after_id)
        self.preview_after_id = self.after(250, self.update_live_preview)

    def update_live_preview(self):
        """Full preview pipeline: collect → generate → analyse → render."""
        if not MATPLOTLIB_AVAILABLE:
            return

        template_name = self.template_var.get()

        # 1. Collect params (with defaults for blanks — never raises)
        params = self._collect_params()

        # 2. Generate entities via preview_engine (pure, no GUI state)
        try:
            entities = preview_engine.generate_preview_entities(template_name, params)
        except Exception:
            self.preview_ax.clear()
            self.preview_ax.set_title('Preview unavailable')
            self.preview_canvas.draw()
            return

        # 3. Run fabrication analysis on the freshly generated entities.
        #    This updates self.fabrication_issues and the warnings panel.
        #    It does NOT call update_live_preview — no loops possible.
        self._run_analysis(template_name, params, entities)

        # 4. Render
        self._render_preview(template_name, entities)

    def _render_preview(self, template_name: str, entities: List[Dict]) -> None:
        """Clear the embedded canvas and redraw entities + axis decorations."""
        self.preview_ax.clear()
        self.preview_ax.set_facecolor('#f9fafc')
        bounds = preview_engine.render_entities(
            self.preview_ax, entities, issues=self.fabrication_issues
        )
        preview_engine.apply_ax_style(
            self.preview_ax, template_name, bounds,
            accent_color=_CLR_ACCENT, border_color=_CLR_BORDER,
        )
        self.preview_canvas.draw()

    # ── Fabrication analysis ─────────────────────────────────────────────────

    def _run_analysis(
        self,
        template_name: str,
        params: Dict,
        entities: List[Dict],
    ) -> None:
        """
        Run FabricationAdvisor on pre-generated entities and update the panel.

        Always receives entities from the caller — never generates them itself,
        so there is no risk of triggering preview updates.
        """
        try:
            tool_diameter = float(self.tool_diameter_var.get())
            if tool_diameter <= 0:
                raise ValueError("Tool diameter must be positive")
            advisor = FabricationAdvisor(tool_diameter)
            self.fabrication_issues = advisor.analyze_design(
                template_name, params, entities
            )
        except Exception as exc:
            self.advisor_status_label.config(
                text=f'Analysis failed: {exc}', style='StatusErr.TLabel'
            )
            self.fabrication_issues = []
        self.update_warnings_display()

    # ── Full-window preview (separate matplotlib window) ─────────────────────

    def on_preview(self):
        """Open a standalone matplotlib window with the full annotated preview."""
        if not MATPLOTLIB_AVAILABLE:
            messagebox.showerror('Preview Error', 'matplotlib is not installed.')
            return

        template_name = self.template_var.get()
        try:
            params = self._collect_strict_params()
        except ValueError as exc:
            messagebox.showerror('Preview Error', str(exc))
            return

        try:
            entities = preview_engine.generate_preview_entities(template_name, params)
        except Exception as exc:
            messagebox.showerror('Preview Error', f'Failed to generate geometry: {exc}')
            return

        _, ax = plt.subplots(figsize=(10, 8))
        bounds = preview_engine.render_entities(ax, entities, issues=self.fabrication_issues)
        preview_engine.apply_ax_style(ax, f'CNC Preview: {template_name}', bounds)

        # Bounding-box annotation
        if all(v is not None for v in bounds):
            min_x, max_x, min_y, max_y = bounds
            ax.add_patch(plt.Rectangle(
                (min_x, min_y), max_x - min_x, max_y - min_y,
                fill=False, edgecolor='darkblue', linewidth=1.0,
                linestyle='--', alpha=0.7,
            ))
            ax.text(
                min_x, max_y + 5,
                f'Bounding Box: {max_x - min_x:.1f} x {max_y - min_y:.1f} mm',
                fontsize=9, color='darkblue', alpha=0.8,
                bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8),
            )

        # Layer legend
        legend_elements = [
            plt.Line2D([0], [0], color=c, linewidth=lw, linestyle=ls, label=lyr)
            for lyr, (c, lw, ls) in preview_engine.LAYER_STYLES.items()
            if lyr not in ('GROOVE',)  # GROOVE is same as FOLDS — skip duplicate
        ]
        ax.legend(handles=legend_elements, loc='upper right', fontsize=8, framealpha=0.9)

        plt.tight_layout()
        plt.show()

    def update_warnings_display(self):
        """Update the warnings listbox with current issues."""
        self.warnings_listbox.delete(0, tk.END)

        if not self.fabrication_issues:
            self.warnings_listbox.insert(tk.END, "✓ No fabrication issues detected")
            self.warnings_listbox.itemconfig(0, {'fg': 'green'})
            self.advisor_status_label.config(text='Analysis complete - No issues found', style='StatusOk.TLabel')
            return

        # Count issues by severity
        errors = sum(1 for issue in self.fabrication_issues if issue.severity.value == 'error')
        warnings = sum(1 for issue in self.fabrication_issues if issue.severity.value == 'warning')
        infos = sum(1 for issue in self.fabrication_issues if issue.severity.value == 'info')

        # Update status
        if errors > 0:
            status_text = f'Analysis complete - {errors} errors, {warnings} warnings, {infos} suggestions'
            status_color = 'red'
        elif warnings > 0:
            status_text = f'Analysis complete - {warnings} warnings, {infos} suggestions'
            status_color = 'orange'
        else:
            status_text = f'Analysis complete - {infos} suggestions'
            status_color = 'blue'

        self.advisor_status_label.config(text=status_text, foreground=status_color)

        # Add issues to listbox
        for i, issue in enumerate(self.fabrication_issues):
            severity_icon = {'error': '❌', 'warning': '⚠️', 'info': 'ℹ️'}[issue.severity.value]
            display_text = f"{severity_icon} {issue.message}"
            self.warnings_listbox.insert(tk.END, display_text)

            # Color code by severity
            color = {'error': 'red', 'warning': 'orange', 'info': 'blue'}[issue.severity.value]
            self.warnings_listbox.itemconfig(i, {'fg': color})

        # Bind click event to show recommendation
        self.warnings_listbox.bind('<<ListboxSelect>>', self.on_warning_select)

    def on_warning_select(self, event):
        """Handle warning selection to show recommendation."""
        selection = self.warnings_listbox.curselection()
        if selection and self.fabrication_issues:
            index = selection[0]
            if index < len(self.fabrication_issues):
                issue = self.fabrication_issues[index]
                messagebox.showinfo("Fabrication Recommendation",
                                  f"Problem: {issue.message}\n\nRecommendation: {issue.recommendation}")

    def open_output_folder(self):
        folder = os.path.abspath(OUTPUT_DIR)
        if sys.platform.startswith('win'):
            os.startfile(folder)
        elif sys.platform.startswith('darwin'):
            os.system(f'open "{folder}"')
        else:
            os.system(f'xdg-open "{folder}"')

    # ===== PROJECT MANAGEMENT METHODS =====

    def new_project(self):
        """Create a new project."""
        self.project_name_var.set('Untitled Project')
        self.current_project_path = None
        self.project_parts = []
        self.parts_listbox.delete(0, tk.END)
        self.part_name_var.set('')
        self.part_template_var.set('Rectangle')
        self.render_part_fields()
        self.status_label.config(text='New project created', style='StatusOk.TLabel')

    def save_project(self):
        """Save the current project to a JSON file."""
        if not self.project_parts:
            messagebox.showwarning('Save Project', 'No parts in project to save.')
            return

        # Get save path
        initial_file = f"{self.project_name_var.get().replace(' ', '_')}.json"
        file_path = filedialog.asksaveasfilename(
            defaultextension='.json',
            filetypes=[('JSON files', '*.json'), ('All files', '*.*')],
            initialfile=initial_file,
            title='Save Project'
        )

        if not file_path:
            return

        try:
            project_data = {
                'name': self.project_name_var.get(),
                'created': datetime.now().isoformat(),
                'parts': self.project_parts
            }

            with open(file_path, 'w') as f:
                json.dump(project_data, f, indent=2)

            self.current_project_path = file_path
            self.status_label.config(text=f'Project saved: {file_path}', style='StatusOk.TLabel')

        except Exception as exc:
            messagebox.showerror('Save Error', f'Failed to save project: {exc}')

    def load_project(self):
        """Load a project from a JSON file."""
        file_path = filedialog.askopenfilename(
            filetypes=[('JSON files', '*.json'), ('All files', '*.*')],
            title='Load Project'
        )

        if not file_path:
            return

        try:
            with open(file_path, 'r') as f:
                project_data = json.load(f)

            self.project_name_var.set(project_data.get('name', 'Loaded Project'))
            self.project_parts = project_data.get('parts', [])
            self.current_project_path = file_path

            # Update parts list
            self.parts_listbox.delete(0, tk.END)
            for part in self.project_parts:
                self.parts_listbox.insert(tk.END, part['name'])

            self.status_label.config(text=f'Project loaded: {file_path}', style='StatusOk.TLabel')

        except Exception as exc:
            messagebox.showerror('Load Error', f'Failed to load project: {exc}')

    def add_current_part_to_project(self):
        """Add the current part from the DXF generator tab to the project."""
        # Get current part data from the DXF generator
        template_name = self.template_var.get()

        # Get parameters
        params = {}
        try:
            for name, var in self.field_vars.items():
                value = var.get().strip()
                if not value:
                    raise ValueError(f'Enter {name.replace("_", " ")}.')
                params[name] = value

            # Add pattern parameters
            params['pattern_enabled'] = self.pattern_enabled.get()
            if self.pattern_enabled.get():
                params['pattern_type'] = self.pattern_type_var.get()

        except Exception as exc:
            messagebox.showerror('Add Part Error', f'Invalid part parameters: {exc}')
            return

        # Create part data
        part_name = f'{template_name}_{len(self.project_parts) + 1}'
        part_data = {
            'name': part_name,
            'template': template_name,
            'params': params,
            'created': datetime.now().isoformat()
        }

        # Add to project
        self.project_parts.append(part_data)
        self.parts_listbox.insert(tk.END, part_name)
        self.status_label.config(text=f'Part added to project: {part_name}', style='StatusOk.TLabel')

    def remove_part_from_project(self):
        """Remove the selected part from the project."""
        selection = self.parts_listbox.curselection()
        if not selection:
            messagebox.showwarning('Remove Part', 'Select a part to remove.')
            return

        index = selection[0]
        part_name = self.parts_listbox.get(index)

        # Confirm removal
        if not messagebox.askyesno('Remove Part', f'Remove part "{part_name}" from project?'):
            return

        # Remove from project
        del self.project_parts[index]
        self.parts_listbox.delete(index)
        self.status_label.config(text=f'Part removed: {part_name}', style='StatusOk.TLabel')

    def on_part_select(self, event):
        """Handle part selection in the listbox."""
        selection = self.parts_listbox.curselection()
        if not selection:
            return

        index = selection[0]
        part_data = self.project_parts[index]

        # Load part data into editor
        self.part_name_var.set(part_data['name'])
        self.part_template_var.set(part_data['template'])
        self.render_part_fields()

        # Load parameters into fields
        for name, value in part_data['params'].items():
            if name in self.part_field_vars:
                self.part_field_vars[name].set(str(value))

    def on_part_template_change(self, event=None):
        """Handle part template change in the editor."""
        self.render_part_fields()

    def render_part_fields(self):
        """Render the parameter fields for the selected part template."""
        # Clear existing fields
        for child in self.part_params_frame.winfo_children():
            child.destroy()

        template_name = self.part_template_var.get()
        if template_name not in TEMPLATES:
            return

        template = TEMPLATES[template_name]
        self.part_field_vars = {}

        # Render shape parameters
        row = 0
        col = 0
        for idx, (label_text, field_name) in enumerate(template['fields']):
            # 2-column layout
            if idx % 2 == 0:
                col = 0
            else:
                col = 2
                row += 1

            ttk.Label(self.part_params_frame, text=label_text).grid(row=row, column=col, sticky='w', pady=6, padx=(0, 8))
            var = tk.StringVar()
            entry = ttk.Entry(self.part_params_frame, textvariable=var)
            entry.grid(row=row, column=col+1, sticky='ew', pady=6)
            self.part_field_vars[field_name] = var

        # Add pattern fields if applicable
        if 'pattern' in template_name.lower():
            # Add pattern type and parameters
            row += 1
            ttk.Label(self.part_params_frame, text='Pattern Type').grid(row=row, column=0, sticky='w', pady=6, padx=(0, 8))
            pattern_var = tk.StringVar(value='circles')
            pattern_menu = ttk.OptionMenu(self.part_params_frame, pattern_var, 'circles', 'circles', 'squares', 'triangles')
            pattern_menu.grid(row=row, column=1, sticky='ew', pady=6)
            self.part_field_vars['pattern_type'] = pattern_var

            # Pattern parameters
            pattern_fields = [
                ('Pattern Size', 'pattern_size'),
                ('Spacing X', 'spacing_x'),
                ('Spacing Y', 'spacing_y'),
                ('Inner Margin', 'inner_margin')
            ]

            for label_text, field_name in pattern_fields:
                row += 1
                ttk.Label(self.part_params_frame, text=label_text).grid(row=row, column=0, sticky='w', pady=6, padx=(0, 8))
                var = tk.StringVar()
                entry = ttk.Entry(self.part_params_frame, textvariable=var)
                entry.grid(row=row, column=1, sticky='ew', pady=6)
                self.part_field_vars[field_name] = var

    def update_current_part(self):
        """Update the currently selected part with editor values."""
        selection = self.parts_listbox.curselection()
        if not selection:
            messagebox.showwarning('Update Part', 'Select a part to update.')
            return

        index = selection[0]

        # Get updated parameters
        params = {}
        try:
            for name, var in self.part_field_vars.items():
                value = var.get().strip()
                if not value:
                    raise ValueError(f'Enter {name.replace("_", " ")}.')
                params[name] = value
        except Exception as exc:
            messagebox.showerror('Update Error', f'Invalid parameters: {exc}')
            return

        # Update part data
        self.project_parts[index]['name'] = self.part_name_var.get()
        self.project_parts[index]['template'] = self.part_template_var.get()
        self.project_parts[index]['params'] = params
        self.project_parts[index]['modified'] = datetime.now().isoformat()

        # Update listbox display
        self.parts_listbox.delete(index)
        self.parts_listbox.insert(index, self.part_name_var.get())
        self.parts_listbox.selection_set(index)

        self.status_label.config(text=f'Part updated: {self.part_name_var.get()}', foreground='blue')

    def generate_part_dxf(self):
        """Generate DXF for the currently selected part."""
        selection = self.parts_listbox.curselection()
        if not selection:
            messagebox.showwarning('Generate DXF', 'Select a part to generate.')
            return

        index = selection[0]
        part_data = self.project_parts[index]

        try:
            template_name = part_data['template']
            params = part_data['params']

            # Generate filename
            safe_name = part_data['name'].replace(' ', '_').lower()
            filename = f'{safe_name}.dxf'
            output_path = os.path.join(PROJECTS_DIR, filename)

            # Generate DXF
            _generate_dxf_file(template_name, params, output_path)

            self.status_label.config(text=f'Generated: {output_path}', style='StatusOk.TLabel')
            messagebox.showinfo('DXF Generated', f'Part DXF saved to: {output_path}')

        except Exception as exc:
            messagebox.showerror('Generation Error', f'Failed to generate DXF: {exc}')

    def generate_all_parts_dxf(self):
        """Generate DXF files for all parts in the project."""
        if not self.project_parts:
            messagebox.showwarning('Generate DXFs', 'No parts in project.')
            return

        generated_count = 0
        errors = []

        for part_data in self.project_parts:
            try:
                template_name = part_data['template']
                params = part_data['params']

                # Generate filename
                safe_name = part_data['name'].replace(' ', '_').lower()
                filename = f'{safe_name}.dxf'
                output_path = os.path.join(PROJECTS_DIR, filename)

                # Generate DXF
                _generate_dxf_file(template_name, params, output_path)
                generated_count += 1

            except Exception as exc:
                errors.append(f'{part_data["name"]}: {exc}')

        # Report results
        if errors:
            error_text = '\n'.join(errors)
            messagebox.showerror('Generation Errors', f'Some DXFs failed to generate:\n\n{error_text}')
        else:
            messagebox.showinfo('DXFs Generated', f'Successfully generated {generated_count} DXF files in {PROJECTS_DIR}')

        self.status_label.config(text=f'Generated {generated_count} DXF files', style='StatusOk.TLabel')

    def nest_all_parts(self):
        """Run nesting optimization for all parts in the project."""
        if not self.project_parts:
            messagebox.showwarning('Nest Parts', 'No parts in project.')
            return

        # Switch to nesting tab
        self.tab_control.select(self.nesting_tab)

        # Clear existing nesting results
        self.nesting_results = None

        # For now, we'll nest all parts as the same type (first part's template)
        # In a more advanced version, we could handle mixed part types
        first_part = self.project_parts[0]
        template_name = first_part['template']

        # Set nesting template to match first part
        if template_name in TEMPLATES:
            self.nesting_template_var.set(template_name)
            self.render_nesting_fields()

            # Use first part's parameters as template
            params = first_part['params']
            for name, value in params.items():
                if name in self.nesting_field_vars:
                    self.nesting_field_vars[name].set(str(value))

            # Set part count to number of parts in project
            self.part_count_var.set(str(len(self.project_parts)))

            # Run optimization
            self.on_optimize_nesting()

            messagebox.showinfo('Nesting Started', f'Set up nesting for {len(self.project_parts)} parts of type {template_name}')
        else:
            messagebox.showerror('Nesting Error', f'Unsupported template: {template_name}')

    def export_combined_layout(self):
        """Export a combined layout DXF with all parts positioned according to nesting results."""
        if not self.nesting_results or not self.nesting_results['sheets']:
            messagebox.showwarning('Export Layout', 'Run nesting optimization first.')
            return

        try:
            # For now, export the first sheet
            sheet = self.nesting_results['sheets'][0]

            # Create combined DXF
            filename = f'{self.project_name_var.get().replace(" ", "_")}_combined_layout.dxf'
            output_path = os.path.join(PROJECTS_DIR, filename)

            # This would require implementing a combined DXF export function
            # For now, just show a placeholder message
            messagebox.showinfo('Export Layout', f'Combined layout export would save to: {output_path}\n\n(This feature requires additional implementation)')

        except Exception as exc:
            messagebox.showerror('Export Error', f'Failed to export layout: {exc}')

    # ===== PHOTO-TO-DXF METHODS =====

    def load_image(self):
        """Load an image file for processing."""
        file_path = filedialog.askopenfilename(
            filetypes=[('Image files', '*.jpg *.jpeg *.png *.bmp *.tiff'), ('All files', '*.*')],
            title='Select Image'
        )

        if not file_path:
            return

        try:
            # Load image with PIL
            self.photo_image = Image.open(file_path)

            # Convert to OpenCV format (RGB to BGR)
            self.photo_cv_image = cv2.cvtColor(np.array(self.photo_image), cv2.COLOR_RGB2BGR)

            # Reset processing results
            self.photo_edges = None
            self.photo_contours = None
            self.photo_simplified = None

            # Update preview
            self.update_photo_preview()

            self.status_label.config(text=f'Image loaded: {os.path.basename(file_path)}', foreground='blue')

        except Exception as exc:
            messagebox.showerror('Load Error', f'Failed to load image: {exc}')

    def process_image(self):
        """Process the loaded image to extract contours."""
        if self.photo_cv_image is None:
            messagebox.showwarning('Process Image', 'Please load an image first.')
            return

        try:
            # Convert to grayscale
            gray = cv2.cvtColor(self.photo_cv_image, cv2.COLOR_BGR2GRAY)

            # Apply Gaussian blur to reduce noise
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)

            # Edge detection with Canny
            threshold1 = int(self.photo_threshold1_var.get())
            threshold2 = int(self.photo_threshold2_var.get())
            self.photo_edges = cv2.Canny(blurred, threshold1, threshold2)

            # Find contours
            contours, hierarchy = cv2.findContours(self.photo_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            # Filter contours by minimum length
            min_length = int(self.photo_min_contour_var.get())
            filtered_contours = []
            for contour in contours:
                if cv2.arcLength(contour, True) > min_length:
                    filtered_contours.append(contour)

            self.photo_contours = filtered_contours

            # Simplify contours using Douglas-Peucker algorithm
            epsilon = float(self.photo_smoothing_var.get())
            self.photo_simplified = []
            for contour in self.photo_contours:
                # Calculate epsilon as percentage of arc length
                arc_len = cv2.arcLength(contour, True)
                simplified = cv2.approxPolyDP(contour, epsilon * arc_len, True)
                if len(simplified) > 2:  # Keep only polygons with at least 3 points
                    self.photo_simplified.append(simplified)

            # Apply smart geometry recognition if enabled
            if self.photo_smart_geom_enabled.get():
                self.photo_simplified = self.apply_smart_geometry_recognition(self.photo_simplified)

            # Update preview
            self.update_photo_preview()

            geom_type = "smart geometry" if self.photo_smart_geom_enabled.get() else "contours"
            self.status_label.config(text=f'Processed image: {len(self.photo_simplified)} {geom_type} found', foreground='blue')

        except Exception as exc:
            messagebox.showerror('Processing Error', f'Failed to process image: {exc}')

    def apply_smart_geometry_recognition(self, contours):
        """Apply smart geometry recognition to contours."""
        recognized_shapes = []

        for contour in contours:
            shape_recognized = False

            # Try to detect rectangles if enabled
            if self.photo_detect_rectangles.get():
                rectangle = self.detect_rectangle(contour)
                if rectangle:
                    recognized_shapes.append(rectangle)
                    shape_recognized = True
                    continue

            # Try to detect circles if enabled
            if self.photo_detect_circles.get():
                circle = self.detect_circle(contour)
                if circle:
                    recognized_shapes.append(circle)
                    shape_recognized = True
                    continue

            # Try to detect straight lines if enabled
            if self.photo_detect_lines.get():
                lines = self.detect_lines(contour)
                if lines:
                    recognized_shapes.extend(lines)
                    shape_recognized = True
                    continue

            # If no specific shape detected, keep as polyline
            if not shape_recognized:
                recognized_shapes.append(contour)

        # Apply post-processing if enabled
        if self.photo_merge_collinear.get():
            recognized_shapes = self.merge_collinear_segments(recognized_shapes)

        if self.photo_remove_tiny.get():
            recognized_shapes = self.remove_tiny_segments(recognized_shapes)

        return recognized_shapes

    def detect_rectangle(self, contour):
        """Detect if contour is a rectangle."""
        try:
            # Approximate the contour
            epsilon = 0.02 * cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, epsilon, True)

            # Rectangle should have 4 vertices
            if len(approx) == 4:
                # Check if it's convex
                if cv2.isContourConvex(approx):
                    # Calculate aspect ratio to filter out very thin rectangles
                    x, y, w, h = cv2.boundingRect(approx)
                    aspect_ratio = float(w) / h if h > 0 else 0
                    if 0.1 < aspect_ratio < 10:  # Reasonable aspect ratio
                        return approx
        except:
            pass
        return None

    def detect_circle(self, contour):
        """Detect if contour is a circle."""
        try:
            # Fit a minimum enclosing circle
            (x, y), radius = cv2.minEnclosingCircle(contour)
            center = (int(x), int(y))
            radius = int(radius)

            # Check if the contour is reasonably circular
            area = cv2.contourArea(contour)
            perimeter = cv2.arcLength(contour, True)
            circularity = 4 * np.pi * area / (perimeter * perimeter) if perimeter > 0 else 0

            # High circularity indicates a circle
            if circularity > 0.7 and radius > 5:
                # Create a circle representation (we'll handle this in DXF generation)
                return {'type': 'circle', 'center': center, 'radius': radius}
        except:
            pass
        return None

    def detect_lines(self, contour):
        """Detect straight line segments in contour."""
        try:
            lines = []
            points = contour.reshape(-1, 2)

            if len(points) < 2:
                return None

            # Use probabilistic Hough line transform on the contour
            # First, create a binary image of just this contour
            img_height, img_width = self.photo_cv_image.shape[:2]
            contour_img = np.zeros((img_height, img_width), dtype=np.uint8)
            cv2.drawContours(contour_img, [contour], 0, 255, 1)

            # Detect lines
            detected_lines = cv2.HoughLinesP(contour_img, 1, np.pi/180, threshold=20,
                                           minLineLength=20, maxLineGap=5)

            if detected_lines is not None:
                # Convert detected lines to contour format
                line_contours = []
                for line in detected_lines:
                    x1, y1, x2, y2 = line[0]
                    line_contour = np.array([[x1, y1], [x2, y2]], dtype=np.int32)
                    line_contours.append(line_contour)
                return line_contours
        except:
            pass
        return None

    def merge_collinear_segments(self, shapes):
        """Merge nearly collinear line segments."""
        # This is a simplified implementation
        # In a full implementation, you'd check angles and distances
        merged = []

        for shape in shapes:
            if isinstance(shape, dict) and shape.get('type') == 'circle':
                # Keep circles as-is
                merged.append(shape)
            else:
                # For polylines, we could implement collinear merging
                # For now, just keep them
                merged.append(shape)

        return merged

    def remove_tiny_segments(self, shapes):
        """Remove very small segments."""
        filtered = []

        for shape in shapes:
            if isinstance(shape, dict) and shape.get('type') == 'circle':
                # Keep circles
                filtered.append(shape)
            else:
                # Check segment lengths
                points = shape.reshape(-1, 2)
                if len(points) >= 2:
                    # Calculate total length
                    total_length = 0
                    for i in range(len(points) - 1):
                        p1, p2 = points[i], points[i + 1]
                        distance = np.sqrt((p2[0] - p1[0])**2 + (p2[1] - p1[1])**2)
                        total_length += distance

                    # Keep if total length is reasonable
                    if total_length > 10:  # Minimum total length threshold
                        filtered.append(shape)

        return filtered

    def update_photo_preview(self):
        """Update the photo preview based on current mode."""
        if not MATPLOTLIB_AVAILABLE or self.photo_cv_image is None:
            return

        # Clear previous plot
        self.photo_ax.clear()

        mode = self.photo_preview_mode.get()

        if mode == 'original':
            # Show original image
            if self.photo_image:
                self.photo_ax.imshow(self.photo_image)
                self.photo_ax.set_title('Original Image')

        elif mode == 'edges':
            # Show edge detection result
            if self.photo_edges is not None:
                self.photo_ax.imshow(self.photo_edges, cmap='gray')
                self.photo_ax.set_title('Edge Detection')
            else:
                self.photo_ax.imshow(self.photo_cv_image)
                self.photo_ax.set_title('Original Image (run processing first)')

        elif mode == 'contours':
            # Show contours overlaid on original
            if self.photo_image:
                self.photo_ax.imshow(self.photo_image)

                if self.photo_simplified:
                    # Draw simplified contours/shapes
                    for shape in self.photo_simplified:
                        if isinstance(shape, dict):
                            # Handle special shape types
                            if shape.get('type') == 'circle':
                                center = shape['center']
                                radius = shape['radius']
                                circle = plt.Circle(center, radius, fill=False, edgecolor='red', linewidth=2)
                                self.photo_ax.add_patch(circle)
                        else:
                            # Handle regular contours
                            points = shape.reshape(-1, 2)
                            if len(points) > 1:
                                self.photo_ax.plot(points[:, 0], points[:, 1], 'r-', linewidth=2)

                geom_type = "Smart Geometry" if self.photo_smart_geom_enabled.get() else "Contours"
                self.photo_ax.set_title(f'{geom_type} ({len(self.photo_simplified) if self.photo_simplified else 0} found)')
            else:
                self.photo_ax.imshow(np.zeros((100, 100)), cmap='gray')
                self.photo_ax.set_title('No image loaded')

        # Remove axis ticks for cleaner look
        self.photo_ax.set_xticks([])
        self.photo_ax.set_yticks([])

        # Redraw the canvas
        self.photo_canvas.draw()

    def generate_photo_dxf(self):
        """Generate DXF file from processed contours."""
        if not self.photo_simplified:
            messagebox.showwarning('Generate DXF', 'Please process an image first.')
            return

        try:
            # Get scaling factor
            scale_factor = float(self.photo_scale_var.get())

            # Check if target dimensions are specified
            target_width = self.photo_target_width_var.get().strip()
            target_height = self.photo_target_height_var.get().strip()

            if target_width and target_height:
                # Calculate scale based on target dimensions
                img_height, img_width = self.photo_cv_image.shape[:2]
                target_w = float(target_width)
                target_h = float(target_height)
                scale_x = target_w / img_width
                scale_y = target_h / img_height
                scale_factor = min(scale_x, scale_y)  # Use the smaller scale to fit

            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'photo_contours_{timestamp}.dxf'
            output_path = os.path.join(OUTPUT_DIR, filename)

            # Create DXF
            self.create_contour_dxf(self.photo_simplified, output_path, scale_factor)

            self.status_label.config(text=f'DXF generated: {output_path}', style='StatusOk.TLabel')
            messagebox.showinfo('DXF Generated', f'Contour DXF saved to: {output_path}')

        except Exception as exc:
            messagebox.showerror('DXF Generation Error', f'Failed to generate DXF: {exc}')

    def _photo_send_to_editor(self) -> None:
        """Convert processed photo contours to entity dicts and push to Interactive Editor."""
        if not self.photo_simplified:
            messagebox.showwarning('Send to Editor', 'Please process an image first.')
            return
        try:
            scale = float(self.photo_scale_var.get())
        except (ValueError, AttributeError):
            scale = 1.0

        entities: list = []
        img_h = self.photo_cv_image.shape[0] if self.photo_cv_image is not None else 0

        for shape in self.photo_simplified:
            if isinstance(shape, dict):
                stype = shape.get('type')
                if stype == 'circle':
                    cx, cy = shape['center']
                    entities.append(em.make_circle(
                        (cx * scale, (img_h - cy) * scale),
                        shape['radius'] * scale,
                        layer=em.LAYER_HOLES,
                        source='photo',
                    ))
                elif stype in ('line', 'polyline'):
                    pts = shape.get('points', [])
                    if len(pts) >= 2:
                        entities.append(em.make_polyline(
                            [(x * scale, (img_h - y) * scale) for x, y in pts],
                            layer=em.LAYER_CUT,
                            source='photo',
                        ))
            else:
                # Raw OpenCV contour array (shape: N×1×2)
                try:
                    pts = [(float(p[0][0]) * scale, (img_h - float(p[0][1])) * scale)
                           for p in shape]
                except (IndexError, TypeError):
                    pts = [(float(p[0]) * scale, (img_h - float(p[1])) * scale)
                           for p in shape.reshape(-1, 2)]
                if len(pts) >= 2:
                    entities.append(em.make_polyline(pts, layer=em.LAYER_CUT, source='photo'))

        if not entities:
            messagebox.showwarning('Send to Editor', 'No valid contours to send.')
            return

        em.ensure_ids(entities)
        self._editor_entities.clear()
        self._editor_entities.extend(entities)
        self.interactive_canvas.set_entities(self._editor_entities)
        self.tab_control.select(self.editor_tab)
        self.status_label.config(
            text=f'Sent {len(entities)} photo contours to editor',
            style='StatusOk.TLabel',
        )

    def create_contour_dxf(self, contours, output_path, scale_factor):
        """Create DXF file from contour data."""
        from ezdxf import new

        # Create a new DXF document
        doc = new('R2010')
        msp = doc.modelspace()

        # Process each contour/shape
        for shape in contours:
            if isinstance(shape, dict):
                # Handle special shape types
                if shape.get('type') == 'circle':
                    center = shape['center']
                    radius = shape['radius']
                    # Scale center and radius
                    scaled_center = (center[0] * scale_factor, -center[1] * scale_factor)
                    scaled_radius = radius * scale_factor
                    msp.add_circle(scaled_center, scaled_radius)
                # Add other shape types here as needed
            else:
                # Handle regular contours
                points = shape.reshape(-1, 2)

                # Scale points
                scaled_points = [(x * scale_factor, -y * scale_factor) for x, y in points]  # Flip Y for DXF coordinate system

                if len(scaled_points) > 1:
                    if len(scaled_points) == 2:
                        # Line segment
                        start, end = scaled_points
                        msp.add_line(start, end)
                    else:
                        # Polyline for closed shapes
                        msp.add_lwpolyline(scaled_points, close=True)

        # Save the DXF file
        doc.saveas(output_path)

    def clear_image(self):
        """Clear the loaded image and reset processing."""
        self.photo_image = None
        self.photo_cv_image = None
        self.photo_edges = None
        self.photo_contours = None
        self.photo_simplified = None

        # Update preview
        self.update_photo_preview()

        self.status_label.config(text='Image cleared', style='StatusOk.TLabel')


if __name__ == '__main__':
    app = CNCGeneratorGUI()
    app.mainloop()
