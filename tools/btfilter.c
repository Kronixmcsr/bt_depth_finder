// Lists chunks that will really contain buried treasure in MC 1.16.1:
// passes the 1% structure roll AND has a beach / snowy beach biome there.
// usage: btfilter <seed> <radius_in_chunks>   -> lines "cx cz"
#include <stdio.h>
#include <stdlib.h>
#include "cubiomes/generator.h"
#include "cubiomes/finders.h"

int main(int argc, char **argv)
{
    if (argc < 3) { fprintf(stderr, "usage: %s seed radius\n", argv[0]); return 1; }
    uint64_t seed = (uint64_t) strtoll(argv[1], NULL, 10);
    int r = atoi(argv[2]);

    Generator g;
    setupGenerator(&g, MC_1_16_1, 0);
    applySeed(&g, DIM_OVERWORLD, seed);

    long rolls = 0, hits = 0;
    for (int cx = -r; cx < r; cx++) {
        for (int cz = -r; cz < r; cz++) {
            Pos p;
            if (!getStructurePos(Treasure, MC_1_16_1, seed, cx, cz, &p)) continue;
            rolls++;
            if (!isViableStructurePos(Treasure, &g, p.x, p.z, 0)) continue;
            printf("%d %d\n", cx, cz);
            hits++;
        }
    }
    fprintf(stderr, "btfilter: %ld RNG hits, %ld in beach biomes (%.1f%%)\n",
            rolls, hits, rolls ? 100.0 * hits / rolls : 0.0);
    return 0;
}
