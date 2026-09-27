// sample_arx.go — synthetic analysis target for the #301 oracle-case
// admission fixtures (kunglao-agent). NOT malware; no real workspace data.
//
// It embeds the SHA-1 family constant K0 = 0x5A827999 (the static,
// byte-anchored artifact the C1 "constant-hit" contract names) and a toy
// ARX step (the reproduction artifact the C2 "pair-match" contract counts
// against tests/fixtures/oracle301/captured_pairs.json):
//
//	out[i] = ((in[i] + rotl(i+1, (i%31)+1) + 0x9E3779B9) mod 2^32)
//	         XOR 0x5A827999
package main

import "fmt"

// k0 is the SHA-1 round constant 0x5A827999 (t = 0..19).
const k0 uint32 = 0x5A827999

// arxStep is one toy ARX round: add-rotate-xor against k0.
func arxStep(x, y, z uint32, rot uint) uint32 {
	return (x + ((y << rot) | (y >> (32-rot))) + z) ^ k0
}

// derive runs the fixture pipeline over 14 synthetic inputs; z is the
// golden-ratio fractional 0x9E3779B9, rot cycles 1..31.
func derive(params [14]uint32) [14]uint32 {
	var out [14]uint32
	for i, p := range params {
		out[i] = arxStep(p, uint32(i+1), 0x9E3779B9, uint(i%31+1))
	}
	return out
}

func main() {
	var params [14]uint32
	for i := range params {
		params[i] = uint32(i)*2654435761 + 1
	}
	for i, v := range derive(params) {
		fmt.Printf("{\"i\": %d, \"in\": %d, \"out\": %d}\n",
			i, params[i], v)
	}
}
