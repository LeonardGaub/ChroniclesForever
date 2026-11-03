"""Small OpenGL helpers on PySide6's own classes (no extra GL binding): shader programs, buffers from numpy, the
constants the 3D stage uses and matrix maths (numpy, row-major, uploaded as QMatrix4x4)."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtGui import QMatrix4x4, QOpenGLContext
from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLShader, QOpenGLShaderProgram, QOpenGLVertexArrayObject
from shiboken6 import VoidPtr

TRIANGLES, TRIANGLE_STRIP = 0x0004, 0x0005
UNSIGNED_SHORT, UNSIGNED_INT, FLOAT = 0x1403, 0x1405, 0x1406
DEPTH_TEST, BLEND, CULL_FACE, POLYGON_OFFSET_FILL = 0x0B71, 0x0BE2, 0x0B44, 0x8037
SRC_ALPHA, ONE_MINUS_SRC_ALPHA, ONE, ZERO = 0x0302, 0x0303, 1, 0
LESS, LEQUAL, GREATER, ALWAYS = 0x0201, 0x0203, 0x0204, 0x0207
COLOR_BUFFER_BIT, DEPTH_BUFFER_BIT = 0x4000, 0x0100

VERSION = "#version 330 core\n"
NO_OFFSET = VoidPtr(0)    # index data from the start of the bound buffer (PySide6 rejects a plain 0)


def functions():
    return QOpenGLContext.currentContext().functions()


def blend(on: bool = True) -> None:
    """Alpha blending that leaves the framebuffer's alpha at 1: Qt composites the QOpenGLWidget's picture as
    premultiplied, so a lower alpha there would let the window show through in false colours."""
    f = functions()
    if on:
        f.glEnable(BLEND)
        f.glBlendFuncSeparate(SRC_ALPHA, ONE_MINUS_SRC_ALPHA, ZERO, ONE)
    else:
        f.glDisable(BLEND)


_LOCATIONS: dict[int, dict[str, int]] = {}      # program -> uniform name -> location (a lookup costs time)


def uniform(prog: QOpenGLShaderProgram, name: str, *values) -> None:
    """Sets a uniform of the bound program: a QMatrix4x4, 1-4 floats, or ints for int/ivec uniforms (PySide6 only
    takes locations, and passes Python ints to float uniforms otherwise)."""
    cache = _LOCATIONS.setdefault(id(prog), {})
    loc = cache.get(name)
    if loc is None:
        loc = cache[name] = prog.uniformLocation(name)
    if loc < 0:
        return
    if len(values) == 1 and isinstance(values[0], QMatrix4x4):
        prog.setUniformValue(loc, values[0])
        return
    f = functions()
    if all(isinstance(v, (int, np.integer)) and not isinstance(v, bool) for v in values):
        (f.glUniform1i, f.glUniform2i, f.glUniform3i, f.glUniform4i)[len(values) - 1](loc, *[int(v) for v in values])
    else:
        (f.glUniform1f, f.glUniform2f, f.glUniform3f, f.glUniform4f)[len(values) - 1](loc, *[float(v) for v in values])


def program(vertex: str, fragment: str) -> QOpenGLShaderProgram:
    p = QOpenGLShaderProgram()
    for kind, src in ((QOpenGLShader.ShaderTypeBit.Vertex, vertex), (QOpenGLShader.ShaderTypeBit.Fragment, fragment)):
        if not p.addShaderFromSourceCode(kind, VERSION + src):
            raise RuntimeError(p.log())
    if not p.link():
        raise RuntimeError(p.log())
    return p


def buffer(data: np.ndarray, index: bool = False) -> QOpenGLBuffer:
    b = QOpenGLBuffer(QOpenGLBuffer.Type.IndexBuffer if index else QOpenGLBuffer.Type.VertexBuffer)
    b.create()
    b.bind()
    raw = np.ascontiguousarray(data).tobytes()
    b.allocate(raw, len(raw))
    return b


class Mesh:
    """A vertex array: float attributes interleaved in one buffer (attrs: name -> size), optional indices."""

    def __init__(self, prog: QOpenGLShaderProgram, vertices: np.ndarray, attrs: dict[str, int],
                 indices: np.ndarray | None = None, shared_indices: "Mesh | None" = None):
        self.vao = QOpenGLVertexArrayObject()
        self.vao.create()
        self.vao.bind()
        self.vbo = buffer(vertices.astype(np.float32))
        stride = 4 * sum(attrs.values())
        offset = 0
        for name, size in attrs.items():
            loc = prog.attributeLocation(name)
            if loc >= 0:
                prog.enableAttributeArray(loc)
                prog.setAttributeBuffer(loc, FLOAT, offset, size, stride)
            offset += 4 * size
        self.count = len(vertices)
        self.ibo, self.index_type = None, UNSIGNED_INT
        if shared_indices is not None:
            self.ibo, self.count, self.index_type = shared_indices.ibo, shared_indices.count, shared_indices.index_type
            self.ibo.bind()
        elif indices is not None:
            self.index_type = UNSIGNED_SHORT if indices.dtype == np.uint16 else UNSIGNED_INT
            self.ibo = buffer(indices, index=True)
            self.count = len(indices)
        self.vao.release()

    def draw_range(self, start: int, count: int, mode: int = TRIANGLES) -> None:
        """count of the mesh's indices from index start."""
        f = functions()
        self.vao.bind()
        size = 2 if self.index_type == UNSIGNED_SHORT else 4
        f.glDrawElements(mode, count, self.index_type, NO_OFFSET if start == 0 else VoidPtr(start * size))
        self.vao.release()

    def draw(self, mode: int = TRIANGLES) -> None:
        f = functions()
        self.vao.bind()
        if self.ibo is not None:
            f.glDrawElements(mode, self.count, self.index_type, NO_OFFSET)
        else:
            f.glDrawArrays(mode, 0, self.count)
        self.vao.release()

    def destroy(self) -> None:
        self.vbo.destroy()
        self.vao.destroy()


class IndexOnly:
    """An index buffer shared by many meshes (every tile's grid)."""

    def __init__(self, indices: np.ndarray):
        self.index_type = UNSIGNED_SHORT if indices.dtype == np.uint16 else UNSIGNED_INT
        self.ibo = buffer(indices, index=True)
        self.count = len(indices)


def grid_indices(rows: int, cols: int) -> np.ndarray:
    """Two triangles per cell of a rows x cols vertex grid (row-major vertex numbering)."""
    r, c = np.mgrid[0:rows - 1, 0:cols - 1]
    a = (r * cols + c).ravel()
    b, d = a + 1, a + cols
    e = d + 1
    tris = np.stack([a, d, b, b, d, e], axis=1).ravel()
    return tris.astype(np.uint16 if rows * cols < 65536 else np.uint32)


def qmatrix(m: np.ndarray) -> QMatrix4x4:
    return QMatrix4x4(*[float(v) for v in m.ravel()])


def perspective(fov_y: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1 / math.tan(fov_y / 2)
    return np.array([[f / aspect, 0, 0, 0],
                     [0, f, 0, 0],
                     [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
                     [0, 0, -1, 0]], np.float64)


def look_at(eye: np.ndarray, target: np.ndarray, up=(0.0, 0.0, 1.0)) -> np.ndarray:
    fwd = target - eye
    fwd = fwd / np.linalg.norm(fwd)
    side = np.cross(fwd, up)
    side = side / np.linalg.norm(side)
    upv = np.cross(side, fwd)
    m = np.identity(4)
    m[0, :3], m[1, :3], m[2, :3] = side, upv, -fwd
    m[:3, 3] = -m[:3, :3] @ eye
    return m
