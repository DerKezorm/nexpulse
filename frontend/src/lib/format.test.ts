import { ms } from './format'

describe('ms', () => {
  it('keeps a decimal below ten milliseconds', () => {
    // Ein iperf3-Server im eigenen Netz antwortet in Bruchteilen einer Millisekunde.
    expect(ms(0.45)).toMatch(/^0[.,]5$/)
    expect(ms(4.2)).toMatch(/^4[.,]2$/)
  })

  it('rounds to whole milliseconds above that', () => {
    expect(ms(12.4)).toBe('12')
    expect(ms(148.6)).toBe('149')
  })

  it('still does what the caller asks', () => {
    expect(ms(148.62, 1)).toMatch(/^148[.,]6$/)
    expect(ms(0.45, 0)).toBe('0')
  })

  it('has nothing to show without a value', () => {
    expect(ms(null)).toBe('–')
    expect(ms(undefined)).toBe('–')
  })
})
