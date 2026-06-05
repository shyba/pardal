"""Port of `app.freerouting.board.Layer` (minimal fields)."""

@fieldwise_init
struct Layer(Copyable, Movable):
    var name: String
    var is_signal: Bool

