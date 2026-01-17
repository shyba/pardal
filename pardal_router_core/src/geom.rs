use crate::router::Point;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Rect {
    pub x0: usize,
    pub y0: usize,
    pub x1: usize,
    pub y1: usize,
}

impl Rect {
    pub fn new(x0: usize, y0: usize, x1: usize, y1: usize) -> Self {
        Self { x0, y0, x1, y1 }
    }

    pub fn is_empty(&self) -> bool {
        self.x0 >= self.x1 || self.y0 >= self.y1
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Circle {
    pub center: Point,
    pub r: usize,
}

impl Circle {
    pub fn new(center: Point, r: usize) -> Self {
        Self { center, r }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Polygon {
    pub vertices: Vec<Point>,
}

impl Polygon {
    pub fn new(vertices: Vec<Point>) -> Self {
        Self { vertices }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LayeredPolygon {
    pub layer: usize,
    pub polygon: Polygon,
}

impl LayeredPolygon {
    pub fn new(layer: usize, polygon: Polygon) -> Self {
        Self { layer, polygon }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Via {
    pub center: Point,
    pub r: usize,
    pub layers: Vec<usize>,
}

impl Via {
    pub fn new(center: Point, r: usize, layers: Vec<usize>) -> Self {
        Self { center, r, layers }
    }
}
