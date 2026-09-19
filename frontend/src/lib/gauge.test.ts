import { position, scaleStops } from '../lib/gauge'

describe('gauge scale', () => {
  it('uses the Ookla-like scale up to a gigabit', () => {
    expect(scaleStops(500)).toEqual([0, 10, 50, 100, 250, 500, 750, 1000])
    expect(scaleStops(1000)).toEqual([0, 10, 50, 100, 250, 500, 750, 1000])
  })

  it('grows for faster lines', () => {
    expect(scaleStops(2300)[7]).toBe(2500)
    expect(scaleStops(8000)[7]).toBe(10000)
  })

  it('places values between the stops', () => {
    const stops = scaleStops(1000)
    expect(position(0, stops)).toBe(0)
    expect(position(1000, stops)).toBe(1)
    expect(position(5000, stops)).toBe(1)
    // 50 liegt auf der dritten Marke von acht.
    expect(position(50, stops)).toBeCloseTo(2 / 7)
    // Halb zwischen 100 und 250.
    expect(position(175, stops)).toBeCloseTo(3.5 / 7)
  })
})
