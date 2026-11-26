// Funzioni pure della UI, senza browser: node test-util.mjs
import assert from 'node:assert/strict'
import { barToBeat, beatToBar, clipAt, daVista, fmtPos, fmtTime, isBlack, noteAt, notesFromList, notesToList, parsePitch, pitchName, rangeFor, scalePcs, snap } from './src/util.js'

assert.equal(pitchName(60), 'C4')
assert.equal(pitchName(61), 'C#4')
assert.equal(parsePitch('A4'), 69)
assert.equal(parsePitch('Bb3'), 58)
assert.equal(parsePitch(64), 64)
assert.ok(isBlack(61) && !isBlack(60))

assert.equal(barToBeat(1, 4), 0)
assert.equal(barToBeat(3, 4), 8)
assert.equal(beatToBar(6, 3), 3)
assert.equal(snap(1.13, 0.25), 1.25)
assert.equal(snap(1.13, 0), 1.13)
assert.equal(snap(0.4, 1 / 3), 0.3333)

assert.equal(fmtPos(0, 4), '1.1')
assert.equal(fmtPos(5, 4), '2.2')
assert.equal(fmtTime(75.25), '1:15.3')

const n = notesFromList([['C4', 0, 1, 100], ['E4', 1, 0.5, 90]])
assert.deepEqual(n[1], { pitch: 64, start: 1, length: 0.5, velocity: 90 })
assert.deepEqual(notesToList(n), [[60, 0, 1, 100], [64, 1, 0.5, 90]])
assert.equal(noteAt(n, 1.2, 64), 1)
assert.equal(noteAt(n, 3, 64), -1)

assert.equal(clipAt([{ bar: 1, bars: 4 }, { bar: 5, bars: 2 }], 5.5, 4).bar, 5)
assert.deepEqual(rangeFor('cutoff', 4000), [20, 18000])
assert.deepEqual(scalePcs('A', 'minor'), [9, 11, 0, 2, 4, 5, 7])

const v = daVista([{ role: 'user', text: 'hi' }, { role: 'assistant', text: 'ok', tools: [{ name: 'add_drums', state: 'ok', input: {} }] }])
assert.deepEqual(v.map(m => m.role), ['user', 'tool', 'assistant'])

console.log('util ok')
