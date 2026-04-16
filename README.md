# CNC DXF Generator

A modular Python application for generating DXF files for CNC machining with various geometric shapes and hole patterns.

## Features

- **Shapes**: Rectangle, Circle, Triangle, Rounded Rectangle, Ellipse, Hexagon
- **Hole Patterns**: No holes, Center hole, Relative holes, Custom holes
- **Validation**: Automatic validation to ensure holes fit within shape boundaries
- **Modular Design**: Clean separation of concerns for easy maintenance and extension

## Project Structure

```
cnc_app/
├── validation.py      # Geometric validation functions
├── shapes.py          # Shape generation functions
├── holes.py           # Hole pattern classes and functions
├── dxf_generator.py   # Main DXF generation logic
├── main.py            # CLI interface
└── README.md          # This file
```

## Installation

1. Ensure Python 3.7+ is installed
2. Install required dependencies:
   ```bash
   pip install ezdxf
   ```

## Usage

### CLI Interface

Run the main script for interactive DXF generation:

```bash
python main.py
```

### Programmatic Usage

Import and use the modules directly for GUI or AI integration:

```python
from dxf_generator import create_rectangle_dxf
from holes import CenterHole

# Create a rectangle with a center hole
hole_pattern = CenterHole(hole_radius=5.0)
create_rectangle_dxf(width=100, height=50, hole_pattern=hole_pattern, filename="my_part.dxf")
```

### Hole Patterns

- **NoHoles**: No holes in the shape
- **CenterHole**: Single hole at the center of the shape
- **RelativeHoles**: Holes positioned relative to shape edges/corners
- **CustomHoles**: User-defined hole positions

Example:

```python
from holes import RelativeHoles, CustomHoles

# Relative holes with 10mm offset
relative_holes = RelativeHoles(hole_radius=3.0, offset_x=10, offset_y=10)

# Custom holes at specific positions
custom_holes = CustomHoles(hole_radius=2.0, positions=[(20, 20), (80, 20), (50, 40)])
```

## GUI Integration

The modular design makes it easy to integrate with GUI frameworks:

```python
# Example with tkinter or any GUI framework
def generate_dxf_from_gui(shape_type, params, hole_pattern):
    if shape_type == "rectangle":
        create_rectangle_dxf(**params, hole_pattern=hole_pattern)
    # ... handle other shapes
```

## AI Integration

The parameterized functions are ready for AI-driven generation:

```python
# AI can call functions with generated parameters
def ai_generate_part(requirements):
    # AI logic to determine shape and hole parameters
    shape_params = {"width": 100, "height": 50}
    hole_pattern = CenterHole(5.0)
    create_rectangle_dxf(**shape_params, hole_pattern=hole_pattern)
```

## API Reference

### Shape Functions (File Output)

- `create_rectangle_dxf(width, height, hole_pattern, filename)`
- `create_circle_dxf(radius, hole_pattern, filename)`
- `create_triangle_dxf(width, height, hole_pattern, filename)`
- `create_rounded_rectangle_dxf(width, height, corner_radius, hole_pattern, filename)`
- `create_ellipse_dxf(rx, ry, hole_pattern, filename)`
- `create_hexagon_dxf(side, hole_pattern, filename)`

### Shape Functions (Memory/Bytes Output)

- `create_rectangle_dxf_bytes(width, height, hole_pattern)`
- `create_circle_dxf_bytes(radius, hole_pattern)`
- `create_triangle_dxf_bytes(width, height, hole_pattern)`
- `create_rounded_rectangle_dxf_bytes(width, height, corner_radius, hole_pattern)`
- `create_ellipse_dxf_bytes(rx, ry, hole_pattern)`
- `create_hexagon_dxf_bytes(side, hole_pattern)`

### Preview Functions

- `get_rectangle_preview(width, height)`
- `get_circle_preview(radius)`
- `get_triangle_preview(width, height)`
- `get_rounded_rectangle_preview(width, height, corner_radius)`
- `get_ellipse_preview(rx, ry)`
- `get_hexagon_preview(side)`

### Hole Classes

All hole classes inherit from `HolePattern` and implement:
- `get_holes(shape_params)`: Returns list of (x, y) positions
- `validate_holes(holes, shape_params)`: Validates hole positions

## Extending the System

### Adding New Shapes

1. Add shape generation function in `shapes.py`
2. Add validation logic in `validation.py` if needed
3. Add hole positioning logic in `holes.py` for each hole pattern
4. Add convenience function in `dxf_generator.py`

### Adding New Hole Patterns

1. Create new class inheriting from `HolePattern`
2. Implement `get_holes()` and `validate_holes()` methods
3. Handle the new pattern in shape-specific logic

## License

This project is open source. Feel free to use and modify as needed.