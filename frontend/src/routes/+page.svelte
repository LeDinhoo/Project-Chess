<script lang="ts">
	import { onMount } from 'svelte';
	import { Chessground } from '@lichess-org/chessground';
	import '@lichess-org/chessground/assets/chessground.base.css';
	import '@lichess-org/chessground/assets/chessground.brown.css';
	import '@lichess-org/chessground/assets/chessground.cburnett.css';

	let boardElement = $state<HTMLDivElement>();

	onMount(() => {
		if (!boardElement) return;

		const ground = Chessground(boardElement, {
			fen: 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
			viewOnly: true
		});

		return () => ground.destroy();
	});
</script>

<div class="board" bind:this={boardElement}></div>

<style>
	.board {
		width: min(90vw, 480px);
		aspect-ratio: 1;
	}
</style>
